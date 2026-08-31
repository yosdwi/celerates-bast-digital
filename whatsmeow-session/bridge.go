package main

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"sync"
	"time"

	"go.mau.fi/whatsmeow"
	"go.mau.fi/whatsmeow/proto/waE2E"
	"go.mau.fi/whatsmeow/types"
	"go.mau.fi/whatsmeow/types/events"
	"google.golang.org/protobuf/proto"
)

const evidenceInGroupReply = "Upload evidence-nya lewat chat pribadi ke aku ya, bukan di grup 🙏 Tinggal kirim foto/dokumennya langsung ke DM aku."

var groupTrigger = regexp.MustCompile(`(?i)^\s*[@!/]?\s*bast\s*bot\b|^\s*!bast\b|^\s*@\s*conform\b`)

type workerResult struct {
	OK   bool   `json:"ok"`
	Text string `json:"text"`
}

type bridge struct {
	client     *whatsmeow.Client
	state      *runtimeState
	menus      *menuStore
	httpClient *http.Client
	workerURL  string
	dataDir    string
	waitDelay  time.Duration
}

func newBridge(client *whatsmeow.Client, state *runtimeState) *bridge {
	workerURL := strings.TrimRight(os.Getenv("BOT_WORKER_BASE_URL"), "/")
	if workerURL == "" {
		workerURL = "http://127.0.0.1:8091"
	}
	dataDir := os.Getenv("BOT_DATA_DIR")
	if dataDir == "" {
		dataDir = "./data"
	}
	delay := 2500 * time.Millisecond
	if raw := os.Getenv("BOT_WAIT_NOTICE_DELAY_MS"); raw != "" {
		if parsed, err := time.ParseDuration(raw + "ms"); err == nil {
			delay = parsed
		}
	}
	return &bridge{
		client:     client,
		state:      state,
		menus:      newMenuStore(),
		httpClient: &http.Client{Timeout: 90 * time.Second},
		workerURL:  workerURL,
		dataDir:    dataDir,
		waitDelay:  delay,
	}
}

func (b *bridge) callWorker(ctx context.Context, payload any) workerResult {
	body, err := json.Marshal(payload)
	if err != nil {
		return workerResult{Text: "marshal request: " + err.Error()}
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, b.workerURL+"/internal/v1/reply", bytes.NewReader(body))
	if err != nil {
		return workerResult{Text: "prepare worker request: " + err.Error()}
	}
	req.Header.Set("content-type", "application/json")
	req.Header.Set("x-bridge-token", configuredToken())
	resp, err := b.httpClient.Do(req)
	if err != nil {
		return workerResult{Text: "bot-worker unreachable: " + err.Error()}
	}
	defer resp.Body.Close()
	limited := io.LimitReader(resp.Body, 2<<20)
	var result workerResult
	if err := json.NewDecoder(limited).Decode(&result); err != nil {
		return workerResult{Text: fmt.Sprintf("bot-worker returned invalid response (HTTP %d): %v", resp.StatusCode, err)}
	}
	return result
}

func (b *bridge) eventHandler(raw any) {
	switch evt := raw.(type) {
	case *events.Connected:
		b.state.setConnection("connected")
		if b.client.Store.ID != nil {
			b.state.setMe(b.client.Store.ID.String())
		}
		b.state.logf("whatsmeow connected as %s", b.state.snapshot().Me)
		go b.refreshGroups()
	case *events.Disconnected:
		b.state.setConnection("disconnected")
		b.state.logf("whatsmeow websocket disconnected; library auto-reconnect remains enabled")
	case *events.LoggedOut:
		b.state.setConnection("logged-out")
		b.state.logf("whatsmeow logged out (on_connect=%t reason=%s); auth DB preserved for diagnosis", evt.OnConnect, evt.Reason.String())
	case *events.StreamReplaced:
		b.state.setConnection("stream-replaced")
		b.state.logf("whatsmeow stream replaced: another client connected with the same session keys")
	case *events.TemporaryBan:
		b.state.setConnection("temporary-ban")
		b.state.logf("whatsmeow temporary ban: %s", evt.String())
	case *events.ClientOutdated:
		b.state.setConnection("client-outdated")
		b.state.logf("whatsmeow client rejected as outdated")
	case *events.ConnectFailure:
		b.state.logf("whatsmeow connect failure: reason=%s message=%s", evt.Reason.String(), evt.Message)
	case *events.Message:
		if !evt.Info.IsFromMe {
			go b.handleMessage(evt)
		}
	}
}

func (b *bridge) refreshGroups() {
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()
	groups, err := b.client.GetJoinedGroups(ctx)
	if err != nil {
		b.state.logf("group list unavailable: %v", err)
		return
	}
	items := make([]groupInfo, 0, len(groups))
	for _, group := range groups {
		items = append(items, groupInfo{JID: group.JID.String(), Subject: group.Name})
	}
	b.state.setGroups(items)
}

func messageText(msg *waE2E.Message) string {
	if msg == nil {
		return ""
	}
	if text := msg.GetConversation(); text != "" {
		return text
	}
	if ext := msg.GetExtendedTextMessage(); ext != nil && ext.GetText() != "" {
		return ext.GetText()
	}
	if image := msg.GetImageMessage(); image != nil {
		return image.GetCaption()
	}
	if video := msg.GetVideoMessage(); video != nil {
		return video.GetCaption()
	}
	if doc := msg.GetDocumentMessage(); doc != nil {
		return doc.GetCaption()
	}
	return ""
}

func messageContext(msg *waE2E.Message) *waE2E.ContextInfo {
	if msg == nil {
		return nil
	}
	if ext := msg.GetExtendedTextMessage(); ext != nil {
		return ext.GetContextInfo()
	}
	if image := msg.GetImageMessage(); image != nil {
		return image.GetContextInfo()
	}
	if video := msg.GetVideoMessage(); video != nil {
		return video.GetContextInfo()
	}
	if doc := msg.GetDocumentMessage(); doc != nil {
		return doc.GetContextInfo()
	}
	return nil
}

func jidUser(raw string) string {
	jid, err := types.ParseJID(raw)
	if err != nil {
		return ""
	}
	return jid.User
}

func (b *bridge) ownUsers() map[string]struct{} {
	users := make(map[string]struct{})
	if b.client.Store.ID != nil && b.client.Store.ID.User != "" {
		users[b.client.Store.ID.User] = struct{}{}
	}
	if !b.client.Store.LID.IsEmpty() && b.client.Store.LID.User != "" {
		users[b.client.Store.LID.User] = struct{}{}
	}
	return users
}

func (b *bridge) isForUs(evt *events.Message, text string) bool {
	ctx := messageContext(evt.Message)
	if ctx != nil {
		own := b.ownUsers()
		for _, raw := range ctx.GetMentionedJID() {
			if _, ok := own[jidUser(raw)]; ok {
				return true
			}
		}
	}
	return groupTrigger.MatchString(text)
}

func (b *bridge) handleMessage(evt *events.Message) {
	jid := evt.Info.Chat.String()
	if evt.Info.IsGroup {
		b.handleGroup(evt, jid)
		return
	}
	b.handleDM(evt, jid)
}

func (b *bridge) handleGroup(evt *events.Message, jid string) {
	text := messageTextCompat(evt.Message)
	forUs := b.isForUs(evt, text)
	isMedia := evt.Message.GetImageMessage() != nil || evt.Message.GetDocumentMessage() != nil
	if isMedia && forUs {
		if !b.state.isAllowedGroup(jid) {
			b.state.logf("ignored media from unlisted group %s", jid)
			return
		}
		b.state.logf("evidence-in-group redirect for %s", jid)
		_ = b.sendTextReply(context.Background(), evt, evidenceInGroupReply)
		return
	}
	if text == "" || !forUs || !b.state.isAllowedGroup(jid) {
		return
	}
	b.state.logf("command from %s: %.120s", jid, text)
	started := time.Now()
	result := b.callWorkerWithNotice(evt, map[string]any{"kind": "text", "text": text}, !looksLikeConversation(text))
	elapsed := time.Since(started).Seconds()
	if result.OK {
		if file := parseFileReply(result.Text); file != nil {
			if file.Caption != "" {
				file.Caption = fmt.Sprintf("%s (%.1fs)", file.Caption, elapsed)
			}
			if err := b.sendFile(context.Background(), jid, file, evt); err != nil {
				b.state.logf("send group file failed: %v", err)
			} else {
				b.cleanupExport(file.Path)
			}
			return
		}
		_ = b.sendTextReply(context.Background(), evt, fmt.Sprintf("%s\n\n_%.1fs_", result.Text, elapsed))
		return
	}
	_ = b.sendTextReply(context.Background(), evt, b.friendlyError("menjalankan perintah", result.Text))
}

func (b *bridge) handleDM(evt *events.Message, jid string) {
	if evt.Message.GetImageMessage() != nil || evt.Message.GetDocumentMessage() != nil {
		b.handleEvidence(evt, jid)
		return
	}
	text := messageTextCompat(evt.Message)
	if text == "" {
		return
	}
	b.state.logf("dm from %s: %.120s", jid, text)
	resolved := b.menus.resolve(jid, text)
	result := b.callWorkerWithNotice(evt, map[string]any{"kind": "text", "text": resolved, "jid": jid, "channel": "dm"}, !looksLikeDMFastPath(resolved))
	b.sendWorkerReply(evt, jid, result, "menjalankan perintah")
}

func (b *bridge) callWorkerWithNotice(evt *events.Message, payload any, delayed bool) workerResult {
	if !delayed {
		return b.callWorker(context.Background(), payload)
	}
	ch := make(chan workerResult, 1)
	go func() { ch <- b.callWorker(context.Background(), payload) }()
	timer := time.NewTimer(b.waitDelay)
	defer timer.Stop()
	select {
	case result := <-ch:
		return result
	case <-timer.C:
		_ = b.sendTextReply(context.Background(), evt, waitingReply(evt.Info.PushName))
		return <-ch
	}
}

func (b *bridge) sendWorkerReply(evt *events.Message, jid string, result workerResult, errorContext string) {
	b.menus.forget(jid)
	if !result.OK {
		_ = b.sendTextReply(context.Background(), evt, b.friendlyError(errorContext, result.Text))
		return
	}
	if interactive := parseInteractiveReply(result.Text); interactive != nil {
		if digitShortcutsEnabled(interactive) {
			b.menus.remember(jid, interactive.Actions)
		}
		_ = b.sendTextReply(context.Background(), evt, fallbackText(interactive))
		return
	}
	if file := parseFileReply(result.Text); file != nil {
		if err := b.sendFile(context.Background(), jid, file, evt); err != nil {
			_ = b.sendTextReply(context.Background(), evt, b.friendlyError("mengirim berkas", err.Error()))
		} else {
			b.cleanupExport(file.Path)
		}
		return
	}
	if strings.TrimSpace(result.Text) == "" {
		result.Text = "(kosong)"
	}
	_ = b.sendTextReply(context.Background(), evt, result.Text)
}

func (b *bridge) friendlyError(contextName, detail string) string {
	ref := fmt.Sprintf("%x", time.Now().UnixNano())
	b.state.logf("%s failed [%s]: %s", contextName, ref, detail)
	return fmt.Sprintf("Maaf, proses gagal saat %s.\nCoba lagi beberapa saat atau hubungi admin jika tetap gagal. (ref: %s)", contextName, ref)
}

func (b *bridge) handleEvidence(evt *events.Message, jid string) {
	var (
		data     []byte
		caption  string
		mimetype string
		err      error
	)
	ctx, cancel := context.WithTimeout(context.Background(), 90*time.Second)
	defer cancel()
	if image := evt.Message.GetImageMessage(); image != nil {
		caption, mimetype = image.GetCaption(), image.GetMimetype()
		data, err = b.client.Download(ctx, image)
	} else if doc := evt.Message.GetDocumentMessage(); doc != nil {
		caption, mimetype = doc.GetCaption(), doc.GetMimetype()
		data, err = b.client.Download(ctx, doc)
	}
	if err != nil {
		_ = b.sendTextReply(context.Background(), evt, b.friendlyError("mengunduh foto/dokumen", err.Error()))
		return
	}
	dir := filepath.Join(b.dataDir, "evidence-uploads")
	if err := os.MkdirAll(dir, 0o750); err != nil {
		_ = b.sendTextReply(context.Background(), evt, b.friendlyError("menyimpan evidence", err.Error()))
		return
	}
	file, err := os.CreateTemp(dir, "evidence-*"+evidenceExtension(mimetype))
	if err != nil {
		_ = b.sendTextReply(context.Background(), evt, b.friendlyError("menyimpan evidence", err.Error()))
		return
	}
	path := file.Name()
	defer os.Remove(path)
	if _, err = file.Write(data); err == nil {
		err = file.Close()
	} else {
		_ = file.Close()
	}
	if err != nil {
		_ = b.sendTextReply(context.Background(), evt, b.friendlyError("menyimpan evidence", err.Error()))
		return
	}
	b.state.logf("evidence upload from %s (%d bytes)", jid, len(data))
	result := b.callWorker(context.Background(), map[string]any{"kind": "evidence", "jid": jid, "filePath": path, "caption": caption})
	b.sendWorkerReply(evt, jid, result, "menyimpan evidence")
}

func (b *bridge) sendText(ctx context.Context, rawJID, text string) error {
	jid, err := types.ParseJID(rawJID)
	if err != nil {
		return err
	}
	_, err = b.client.SendMessage(ctx, jid, &waE2E.Message{Conversation: proto.String(text)})
	return err
}

func quotedContext(evt *events.Message) *waE2E.ContextInfo {
	if evt == nil {
		return nil
	}
	return &waE2E.ContextInfo{
		StanzaID:      proto.String(string(evt.Info.ID)),
		Participant:   proto.String(evt.Info.Sender.ToNonAD().String()),
		QuotedMessage: evt.Message,
	}
}

func (b *bridge) sendTextReply(ctx context.Context, evt *events.Message, text string) error {
	if evt == nil {
		return fmt.Errorf("reply event is nil")
	}
	_, err := b.client.SendMessage(ctx, evt.Info.Chat, &waE2E.Message{ExtendedTextMessage: &waE2E.ExtendedTextMessage{
		Text:        proto.String(text),
		ContextInfo: quotedContext(evt),
	}})
	return err
}

func (b *bridge) sendFile(ctx context.Context, rawJID string, payload *filePayload, replyTo *events.Message) error {
	jid, err := types.ParseJID(rawJID)
	if err != nil {
		return err
	}
	data, err := os.ReadFile(payload.Path)
	if err != nil {
		return err
	}
	mime := mimeForPath(payload.Path)
	if strings.HasPrefix(mime, "image/") {
		upload, err := b.client.Upload(ctx, data, whatsmeow.MediaImage)
		if err != nil {
			return err
		}
		_, err = b.client.SendMessage(ctx, jid, &waE2E.Message{ImageMessage: &waE2E.ImageMessage{
			ContextInfo:   quotedContext(replyTo),
			Caption:       proto.String(payload.Caption),
			Mimetype:      proto.String(mime),
			URL:           &upload.URL,
			DirectPath:    &upload.DirectPath,
			MediaKey:      upload.MediaKey,
			FileEncSHA256: upload.FileEncSHA256,
			FileSHA256:    upload.FileSHA256,
			FileLength:    &upload.FileLength,
		}})
		return err
	}
	upload, err := b.client.Upload(ctx, data, whatsmeow.MediaDocument)
	if err != nil {
		return err
	}
	name := payload.Filename
	if name == "" {
		name = filepath.Base(payload.Path)
	}
	_, err = b.client.SendMessage(ctx, jid, &waE2E.Message{DocumentMessage: &waE2E.DocumentMessage{
		ContextInfo:   quotedContext(replyTo),
		Caption:       proto.String(payload.Caption),
		Mimetype:      proto.String(mime),
		FileName:      proto.String(name),
		URL:           &upload.URL,
		DirectPath:    &upload.DirectPath,
		MediaKey:      upload.MediaKey,
		FileEncSHA256: upload.FileEncSHA256,
		FileSHA256:    upload.FileSHA256,
		FileLength:    &upload.FileLength,
	}})
	return err
}

type outboundRecord struct {
	JID     string
	Text    string
	Status  int
	Payload map[string]any
}

type outboundStore struct {
	mu        sync.Mutex
	inFlight  map[string]*outboundCall
	completed map[string]outboundRecord
	order     []string
}

type outboundCall struct {
	JID    string
	Text   string
	Done   chan struct{}
	Result outboundRecord
}

func newOutboundStore() *outboundStore {
	return &outboundStore{inFlight: make(map[string]*outboundCall), completed: make(map[string]outboundRecord)}
}

func validDirectJID(raw string) bool {
	jid, err := types.ParseJID(raw)
	return err == nil && (jid.Server == types.DefaultUserServer || jid.Server == types.HiddenUserServer)
}
