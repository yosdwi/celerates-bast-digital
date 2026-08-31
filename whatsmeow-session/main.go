package main

import (
	"context"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"html"
	"io"
	"log"
	"net/http"
	"os"
	"os/signal"
	"path/filepath"
	"sort"
	"strings"
	"sync"
	"syscall"
	"time"

	_ "github.com/mattn/go-sqlite3"
	qrcode "github.com/skip2/go-qrcode"
	"go.mau.fi/whatsmeow"
	"go.mau.fi/whatsmeow/proto/waE2E"
	"go.mau.fi/whatsmeow/store"
	"go.mau.fi/whatsmeow/store/sqlstore"
	"go.mau.fi/whatsmeow/types"
	waLog "go.mau.fi/whatsmeow/util/log"
	"google.golang.org/protobuf/proto"
)

type groupInfo struct {
	JID     string `json:"jid"`
	Subject string `json:"subject"`
}

type stateSnapshot struct {
	Connection  string      `json:"connection"`
	Me          string      `json:"me"`
	QRDataURL   string      `json:"qrDataUrl,omitempty"`
	PairingCode string      `json:"pairingCode,omitempty"`
	Groups      []groupInfo `json:"groups,omitempty"`
	Logs        []string    `json:"logs,omitempty"`
}

type runtimeState struct {
	mu           sync.RWMutex
	connection   string
	me           string
	qrDataURL    string
	pairingCode  string
	groups       []groupInfo
	logs         []string
	allowedEnv   map[string]struct{}
	allowedFile  string
	allowedSaved map[string]struct{}
}

func newRuntimeState(dataDir string) *runtimeState {
	s := &runtimeState{
		connection:   "starting",
		allowedEnv:   make(map[string]struct{}),
		allowedSaved: make(map[string]struct{}),
		allowedFile:  filepath.Join(dataDir, "config.json"),
	}
	for _, jid := range strings.Split(os.Getenv("BOT_ALLOWED_GROUPS"), ",") {
		if jid = strings.TrimSpace(jid); jid != "" {
			s.allowedEnv[jid] = struct{}{}
		}
	}
	s.loadAllowed()
	return s
}

func (s *runtimeState) loadAllowed() {
	data, err := os.ReadFile(s.allowedFile)
	if err != nil {
		return
	}
	var cfg struct {
		AllowedGroups []string `json:"allowedGroups"`
	}
	if json.Unmarshal(data, &cfg) != nil {
		return
	}
	for _, jid := range cfg.AllowedGroups {
		if jid = strings.TrimSpace(jid); jid != "" {
			s.allowedSaved[jid] = struct{}{}
		}
	}
}

func (s *runtimeState) saveAllowed(groups []string) error {
	clean := make([]string, 0, len(groups))
	seen := make(map[string]struct{})
	for _, jid := range groups {
		jid = strings.TrimSpace(jid)
		if jid == "" {
			continue
		}
		if _, ok := seen[jid]; ok {
			continue
		}
		seen[jid] = struct{}{}
		clean = append(clean, jid)
	}
	sort.Strings(clean)
	data, _ := json.MarshalIndent(map[string]any{"allowedGroups": clean}, "", "  ")
	if err := os.MkdirAll(filepath.Dir(s.allowedFile), 0o750); err != nil {
		return err
	}
	if err := os.WriteFile(s.allowedFile, data, 0o640); err != nil {
		return err
	}
	s.mu.Lock()
	s.allowedSaved = make(map[string]struct{}, len(clean))
	for _, jid := range clean {
		s.allowedSaved[jid] = struct{}{}
	}
	s.mu.Unlock()
	return nil
}

func (s *runtimeState) isAllowedGroup(jid string) bool {
	s.mu.RLock()
	defer s.mu.RUnlock()
	_, env := s.allowedEnv[jid]
	_, saved := s.allowedSaved[jid]
	return env || saved
}

func (s *runtimeState) allowedGroups() map[string]struct{} {
	s.mu.RLock()
	defer s.mu.RUnlock()
	out := make(map[string]struct{}, len(s.allowedEnv)+len(s.allowedSaved))
	for k := range s.allowedEnv {
		out[k] = struct{}{}
	}
	for k := range s.allowedSaved {
		out[k] = struct{}{}
	}
	return out
}

func (s *runtimeState) logf(format string, args ...any) {
	entry := time.Now().UTC().Format(time.RFC3339) + " " + fmt.Sprintf(format, args...)
	log.Print(entry)
	s.mu.Lock()
	defer s.mu.Unlock()
	s.logs = append([]string{entry}, s.logs...)
	if len(s.logs) > 80 {
		s.logs = s.logs[:80]
	}
}

func (s *runtimeState) setConnection(value string) { s.mu.Lock(); s.connection = value; s.mu.Unlock() }
func (s *runtimeState) setMe(value string)         { s.mu.Lock(); s.me = value; s.mu.Unlock() }
func (s *runtimeState) setGroups(value []groupInfo) {
	s.mu.Lock()
	s.groups = append([]groupInfo(nil), value...)
	s.mu.Unlock()
}
func (s *runtimeState) setQR(value string) { s.mu.Lock(); s.qrDataURL = value; s.mu.Unlock() }
func (s *runtimeState) setPairingCode(value string) {
	s.mu.Lock()
	s.pairingCode = value
	s.mu.Unlock()
}

func (s *runtimeState) snapshot() stateSnapshot {
	s.mu.RLock()
	defer s.mu.RUnlock()
	return stateSnapshot{
		Connection:  s.connection,
		Me:          s.me,
		QRDataURL:   s.qrDataURL,
		PairingCode: s.pairingCode,
		Groups:      append([]groupInfo(nil), s.groups...),
		Logs:        append([]string(nil), s.logs...),
	}
}

type app struct {
	state    *runtimeState
	bridge   *bridge
	outbound *outboundStore
	client   *whatsmeow.Client
}

func main() {
	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()

	dataDir := getenv("BOT_DATA_DIR", "./data")
	authDir := getenv("BOT_AUTH_DIR", filepath.Join(dataDir, "auth-whatsmeow"))
	if err := os.MkdirAll(authDir, 0o750); err != nil {
		log.Fatalf("create auth dir: %v", err)
	}
	if err := os.MkdirAll(dataDir, 0o750); err != nil {
		log.Fatalf("create data dir: %v", err)
	}

	state := newRuntimeState(dataDir)
	state.logf("starting whatsmeow transport; auth=%s", authDir)

	if latest, err := whatsmeow.GetLatestVersion(ctx, nil); err != nil {
		state.logf("latest WA web version lookup failed; using library default: %v", err)
	} else {
		store.SetWAVersion(*latest)
		state.logf("using latest WhatsApp Web version %v", latest)
	}

	dbLog := waLog.Stdout("whatsmeow-db", logLevel("BOT_WHATSMEOW_LOG_LEVEL", "INFO"), true)
	dsn := "file:" + filepath.Join(authDir, "session.db") + "?_foreign_keys=on&_busy_timeout=5000&_journal_mode=WAL"
	container, err := sqlstore.New(ctx, "sqlite3", dsn, dbLog)
	if err != nil {
		log.Fatalf("open whatsmeow session store: %v", err)
	}
	defer container.Close()
	device, err := container.GetFirstDevice(ctx)
	if err != nil {
		log.Fatalf("load whatsmeow device: %v", err)
	}
	clientLog := waLog.Stdout("whatsmeow", logLevel("BOT_WHATSMEOW_LOG_LEVEL", "INFO"), true)
	client := whatsmeow.NewClient(device, clientLog)
	bridge := newBridge(client, state)
	client.AddEventHandler(bridge.eventHandler)

	application := &app{state: state, bridge: bridge, outbound: newOutboundStore(), client: client}
	server := &http.Server{
		Addr:              getenv("BOT_SETUP_HOST", "127.0.0.1") + ":" + getenv("BOT_SETUP_PORT", "8090"),
		Handler:           application.routes(),
		ReadHeaderTimeout: 5 * time.Second,
	}
	go func() {
		state.logf("setup/status HTTP on http://%s", server.Addr)
		if err := server.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			state.logf("HTTP server failed: %v", err)
			stop()
		}
	}()

	if device.ID == nil {
		if err := application.connectForPairing(ctx); err != nil {
			state.setConnection("pairing-failed")
			state.logf("pairing startup failed: %v", err)
		}
	} else {
		state.setConnection("connecting")
		if err := client.Connect(); err != nil {
			state.setConnection("failed")
			state.logf("connect failed: %v", err)
		}
	}

	<-ctx.Done()
	state.logf("shutdown requested")
	client.Disconnect()
	shutdownCtx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	_ = server.Shutdown(shutdownCtx)
}

func (a *app) connectForPairing(ctx context.Context) error {
	a.state.setConnection("awaiting-scan")
	qrChan, err := a.client.GetQRChannel(ctx)
	if err != nil {
		return err
	}
	if err := a.client.Connect(); err != nil {
		return err
	}
	pairingNumber := strings.Map(func(r rune) rune {
		if r >= '0' && r <= '9' {
			return r
		}
		return -1
	}, os.Getenv("BOT_PAIRING_NUMBER"))
	go func() {
		pairingRequested := false
		for item := range qrChan {
			switch item.Event {
			case whatsmeow.QRChannelEventCode:
				png, err := qrcode.Encode(item.Code, qrcode.Medium, 320)
				if err == nil {
					a.state.setQR("data:image/png;base64," + base64.StdEncoding.EncodeToString(png))
				}
				a.state.logf("pairing QR refreshed (valid ~%s)", item.Timeout.Round(time.Second))
				if pairingNumber != "" && !pairingRequested {
					pairingRequested = true
					// PairPhone's own doc comment: clientDisplayName "must be formatted
					// as `Browser (OS)`, and only common browsers/OSes are allowed (the
					// server will validate it and return 400 if it's wrong)" -- "Google
					// Chrome" is the branded product name, not a recognized browser
					// token; confirmed live (repeatable 400: bad-request on every
					// attempt). Plain "Chrome" matches WhatsApp's own convention (and
					// wa-session's pre-existing Baileys browser identity in this same
					// project already used bare "Chrome", never "Google Chrome").
					code, err := a.client.PairPhone(context.Background(), pairingNumber, true, whatsmeow.PairClientChrome, "Chrome (Linux)")
					if err != nil {
						a.state.logf("pairing code request failed: %v", err)
					} else {
						a.state.setPairingCode(code)
						a.state.logf("pairing code issued for configured phone")
					}
				}
			case "success":
				a.state.setQR("")
				a.state.setPairingCode("")
				a.state.logf("pairing successful; waiting for authenticated connection")
			case whatsmeow.QRChannelEventError:
				a.state.logf("pairing error: %v", item.Error)
			default:
				if item.Event != "" && item.Event != "timeout" {
					a.state.logf("pairing event: %s", item.Event)
				}
			}
		}
	}()
	return nil
}

func (a *app) routes() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("GET /health", a.health)
	mux.HandleFunc("GET /internal/v1/status", a.status)
	mux.HandleFunc("POST /internal/v1/messages", a.sendOutbound)
	mux.HandleFunc("POST /allow", a.allow)
	mux.HandleFunc("POST /try", a.tryWorker)
	mux.HandleFunc("GET /", a.setupPage)
	return mux
}

func (a *app) health(w http.ResponseWriter, _ *http.Request) {
	s := a.state.snapshot()
	writeJSON(w, http.StatusOK, map[string]any{"connection": s.Connection, "me": s.Me, "transport": "whatsmeow"})
}

func (a *app) status(w http.ResponseWriter, r *http.Request) {
	if !safeEqual(r.Header.Get("x-bridge-token"), configuredToken()) {
		writeJSON(w, http.StatusForbidden, map[string]any{"status": "forbidden"})
		return
	}
	s := a.state.snapshot()
	writeJSON(w, http.StatusOK, map[string]any{"connection": s.Connection, "me": s.Me, "qrDataUrl": nullable(s.QRDataURL), "pairingCode": nullable(s.PairingCode), "transport": "whatsmeow"})
}

func (a *app) sendOutbound(w http.ResponseWriter, r *http.Request) {
	if !safeEqual(r.Header.Get("x-bridge-token"), configuredToken()) {
		writeJSON(w, http.StatusForbidden, map[string]any{"status": "forbidden"})
		return
	}
	if a.state.snapshot().Connection != "connected" || !a.client.IsConnected() || !a.client.IsLoggedIn() {
		writeJSON(w, http.StatusServiceUnavailable, map[string]any{"status": "unavailable", "error": "whatsapp_not_connected"})
		return
	}
	r.Body = http.MaxBytesReader(w, r.Body, 16*1024)
	var payload struct {
		JID       string `json:"jid"`
		Text      string `json:"text"`
		RequestID string `json:"request_id"`
	}
	if err := json.NewDecoder(r.Body).Decode(&payload); err != nil {
		writeJSON(w, http.StatusBadRequest, map[string]any{"status": "invalid", "error": "invalid_json"})
		return
	}
	payload.JID = strings.TrimSpace(payload.JID)
	payload.Text = strings.TrimSpace(payload.Text)
	payload.RequestID = strings.TrimSpace(payload.RequestID)
	if !validDirectJID(payload.JID) || payload.Text == "" || len(payload.Text) > maxMessageChars || payload.RequestID == "" || len(payload.RequestID) > maxRequestIDChars {
		writeJSON(w, http.StatusUnprocessableEntity, map[string]any{"status": "invalid", "error": "invalid_message_request"})
		return
	}
	result := a.sendOutboundOnce(payload.JID, payload.Text, payload.RequestID)
	writeJSON(w, result.Status, result.Payload)
}

func (a *app) sendOutboundOnce(jid, text, requestID string) outboundRecord {
	a.outbound.mu.Lock()
	if completed, ok := a.outbound.completed[requestID]; ok {
		a.outbound.mu.Unlock()
		if completed.JID != jid || completed.Text != text {
			return outboundRecord{Status: http.StatusConflict, Payload: map[string]any{"status": "invalid", "error": "request_id_conflict"}}
		}
		a.state.logf("outbound follow-up deduped request=%s", requestID)
		return completed
	}
	if call, ok := a.outbound.inFlight[requestID]; ok {
		if call.JID != jid || call.Text != text {
			a.outbound.mu.Unlock()
			return outboundRecord{Status: http.StatusConflict, Payload: map[string]any{"status": "invalid", "error": "request_id_conflict"}}
		}
		a.outbound.mu.Unlock()
		<-call.Done
		return call.Result
	}
	call := &outboundCall{JID: jid, Text: text, Done: make(chan struct{})}
	a.outbound.inFlight[requestID] = call
	a.outbound.mu.Unlock()

	ctx, cancel := context.WithTimeout(context.Background(), 75*time.Second)
	defer cancel()
	target, err := types.ParseJID(jid)
	var result outboundRecord
	if err == nil {
		var response whatsmeow.SendResponse
		response, err = a.client.SendMessage(ctx, target, textMessage(text))
		if err == nil {
			result = outboundRecord{JID: jid, Text: text, Status: http.StatusOK, Payload: map[string]any{"status": "sent", "provider_message_id": string(response.ID)}}
		}
	}
	if err != nil {
		a.state.logf("outbound follow-up failed request=%s: %v", requestID, err)
		result = outboundRecord{JID: jid, Text: text, Status: http.StatusServiceUnavailable, Payload: map[string]any{"status": "unavailable", "error": "send_failed"}}
	} else {
		a.state.logf("outbound follow-up sent request=%s provider=%v", requestID, result.Payload["provider_message_id"])
	}

	a.outbound.mu.Lock()
	call.Result = result
	delete(a.outbound.inFlight, requestID)
	if result.Status == http.StatusOK {
		a.outbound.completed[requestID] = result
		a.outbound.order = append(a.outbound.order, requestID)
		if len(a.outbound.order) > maxCompletedSends {
			oldest := a.outbound.order[0]
			a.outbound.order = a.outbound.order[1:]
			delete(a.outbound.completed, oldest)
		}
	}
	close(call.Done)
	a.outbound.mu.Unlock()
	return result
}

func (a *app) allow(w http.ResponseWriter, r *http.Request) {
	if err := r.ParseForm(); err != nil {
		http.Error(w, "invalid form", http.StatusBadRequest)
		return
	}
	if err := a.state.saveAllowed(r.Form["jid"]); err != nil {
		http.Error(w, "failed to save allowlist", http.StatusInternalServerError)
		return
	}
	a.state.logf("allowlist updated (%d grup)", len(r.Form["jid"]))
	http.Redirect(w, r, "/", http.StatusSeeOther)
}

func (a *app) tryWorker(w http.ResponseWriter, r *http.Request) {
	if err := r.ParseForm(); err != nil {
		http.Error(w, "invalid form", http.StatusBadRequest)
		return
	}
	result := a.bridge.callWorker(r.Context(), map[string]any{"kind": "text", "text": r.Form.Get("text")})
	w.Header().Set("content-type", "text/plain; charset=utf-8")
	_, _ = io.WriteString(w, result.Text)
}

func (a *app) setupPage(w http.ResponseWriter, _ *http.Request) {
	s := a.state.snapshot()
	allowed := a.state.allowedGroups()
	var rows strings.Builder
	for _, group := range s.Groups {
		checked := ""
		if _, ok := allowed[group.JID]; ok {
			checked = " checked"
		}
		fmt.Fprintf(&rows, `<tr><td><input type="checkbox" name="jid" value="%s"%s></td><td>%s</td><td><code>%s</code></td></tr>`, html.EscapeString(group.JID), checked, html.EscapeString(group.Subject), html.EscapeString(group.JID))
	}
	if rows.Len() == 0 {
		rows.WriteString(`<tr><td colspan="3">Belum ada grup terbaca. Pastikan bot sudah diundang ke grup.</td></tr>`)
	}
	pairing := "<p>Tidak ada QR aktif.</p>"
	if s.Connection == "connected" {
		pairing = "<p>Sudah terhubung. Tidak perlu pairing lagi.</p>"
	} else if s.QRDataURL != "" {
		pairing = `<img alt="WhatsApp QR" src="` + html.EscapeString(s.QRDataURL) + `" width="320" height="320">`
	}
	if s.PairingCode != "" {
		pairing += `<p>Atau masukkan kode ini di WhatsApp &gt; Tautkan dengan nomor telepon: <strong>` + html.EscapeString(s.PairingCode) + `</strong></p>`
	}
	refresh := ""
	if s.Connection != "connected" {
		refresh = `<meta http-equiv="refresh" content="5">`
	}
	page := `<!doctype html><html lang="id"><head><meta charset="utf-8">` + refresh + `<meta name="viewport" content="width=device-width,initial-scale=1"><title>Setup BAST Bot</title><style>body{font-family:system-ui,sans-serif;margin:2rem auto;max-width:52rem;padding:0 1rem;line-height:1.5}table{border-collapse:collapse;width:100%}td,th{border:1px solid #ddd;padding:.4rem .6rem;text-align:left}code{font-size:.85em}pre{background:#f5f5f5;padding:.75rem;overflow:auto;max-height:18rem}.status{font-weight:600}</style></head><body>` +
		`<h1>Setup BAST Bot — whatsmeow</h1><p class="status">Status: ` + html.EscapeString(s.Connection) + ` — ` + html.EscapeString(s.Me) + `</p><h2>1. Pairing WhatsApp</h2>` + pairing +
		`<h2>2. Grup yang diizinkan</h2><form method="post" action="/allow"><table><thead><tr><th>Aktif</th><th>Nama grup</th><th>JID</th></tr></thead><tbody>` + rows.String() + `</tbody></table><p><button type="submit">Simpan</button></p></form>` +
		`<h2>3. Uji backend</h2><form method="post" action="/try"><p><input name="text" size="60" value="@BAST Bot system status"> <button type="submit">Jalankan</button></p></form><h2>Log</h2><pre>` + html.EscapeString(strings.Join(s.Logs, "\n")) + `</pre></body></html>`
	w.Header().Set("content-type", "text/html; charset=utf-8")
	_, _ = io.WriteString(w, page)
}

func textMessage(text string) *waE2E.Message {
	return &waE2E.Message{Conversation: proto.String(text)}
}

func writeJSON(w http.ResponseWriter, status int, payload any) {
	w.Header().Set("content-type", "application/json; charset=utf-8")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(payload)
}

func nullable(value string) any {
	if value == "" {
		return nil
	}
	return value
}

func getenv(name, fallback string) string {
	if value := strings.TrimSpace(os.Getenv(name)); value != "" {
		return value
	}
	return fallback
}

func logLevel(name, fallback string) string {
	level := strings.ToUpper(getenv(name, fallback))
	switch level {
	case "DEBUG", "INFO", "WARN", "ERROR":
		return level
	default:
		return fallback
	}
}
