package main

import (
	"crypto/subtle"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"
	"sync"
	"time"
)

const (
	maxMessageChars   = 4000
	maxRequestIDChars = 128
	maxCompletedSends = 1024
	pendingMenuTTL    = 15 * time.Minute
	maxPendingMenus   = 512
)

type interactiveAction struct {
	ID    string `json:"id"`
	Label string `json:"label"`
}

type interactivePayload struct {
	Kind           string              `json:"kind"`
	Text           string              `json:"text"`
	Footer         string              `json:"footer"`
	Actions        []interactiveAction `json:"actions"`
	DigitShortcuts *bool               `json:"digitShortcuts,omitempty"`
}

type filePayload struct {
	Kind     string `json:"kind"`
	Path     string `json:"path"`
	Filename string `json:"filename"`
	Caption  string `json:"caption"`
}

type menuEntry struct {
	Actions   []interactiveAction
	ExpiresAt time.Time
}

type menuStore struct {
	mu    sync.Mutex
	items map[string]menuEntry
}

func newMenuStore() *menuStore { return &menuStore{items: make(map[string]menuEntry)} }

func (m *menuStore) remember(jid string, actions []interactiveAction) {
	m.mu.Lock()
	defer m.mu.Unlock()
	copied := append([]interactiveAction(nil), actions...)
	m.items[jid] = menuEntry{Actions: copied, ExpiresAt: time.Now().Add(pendingMenuTTL)}
	if len(m.items) <= maxPendingMenus {
		return
	}
	var oldestKey string
	var oldest time.Time
	for key, entry := range m.items {
		if oldestKey == "" || entry.ExpiresAt.Before(oldest) {
			oldestKey, oldest = key, entry.ExpiresAt
		}
	}
	delete(m.items, oldestKey)
}

func (m *menuStore) forget(jid string) {
	m.mu.Lock()
	defer m.mu.Unlock()
	delete(m.items, jid)
}

func (m *menuStore) resolve(jid, text string) string {
	trimmed := strings.TrimSpace(text)
	if !regexp.MustCompile(`^[0-9]+$`).MatchString(trimmed) {
		return text
	}
	m.mu.Lock()
	defer m.mu.Unlock()
	entry, ok := m.items[jid]
	if !ok || time.Now().After(entry.ExpiresAt) {
		if ok {
			delete(m.items, jid)
		}
		return text
	}
	n, _ := strconv.Atoi(trimmed)
	if n < 1 || n > len(entry.Actions) {
		return text
	}
	return entry.Actions[n-1].ID
}

func parseInteractiveReply(text string) *interactivePayload {
	var payload interactivePayload
	if json.Unmarshal([]byte(text), &payload) != nil || payload.Kind != "interactive" || payload.Text == "" {
		return nil
	}
	filtered := make([]interactiveAction, 0, len(payload.Actions))
	for _, action := range payload.Actions {
		action.ID = strings.TrimSpace(action.ID)
		action.Label = strings.TrimSpace(action.Label)
		if action.ID != "" && action.Label != "" {
			filtered = append(filtered, action)
		}
	}
	payload.Actions = filtered
	if payload.Footer == "" {
		payload.Footer = "Digital BAST"
	}
	return &payload
}

func digitShortcutsEnabled(payload *interactivePayload) bool {
	return payload.DigitShortcuts == nil || *payload.DigitShortcuts
}

func fallbackText(payload *interactivePayload) string {
	lines := []string{payload.Text}
	if len(payload.Actions) > 0 {
		lines = append(lines, "")
		if digitShortcutsEnabled(payload) {
			for i, action := range payload.Actions {
				lines = append(lines, fmt.Sprintf("%d. %s", i+1, action.Label))
			}
		} else {
			for _, action := range payload.Actions {
				lines = append(lines, fmt.Sprintf("• %s: %s", action.Label, action.ID))
			}
		}
	}
	if payload.Footer != "" {
		lines = append(lines, "", "_"+payload.Footer+"_")
	}
	return strings.Join(lines, "\n")
}

func parseFileReply(text string) *filePayload {
	var payload filePayload
	if json.Unmarshal([]byte(text), &payload) != nil || payload.Kind != "file" || strings.TrimSpace(payload.Path) == "" {
		return nil
	}
	return &payload
}

func firstName(pushName string) string {
	re := regexp.MustCompile(`[\p{L}\p{N}]+`)
	return re.FindString(strings.TrimSpace(pushName))
}

func waitingReply(pushName string) string {
	if name := firstName(pushName); name != "" {
		return fmt.Sprintf("Siap kak %s, tunggu sebentar ya aku proses dulu 🙏", name)
	}
	return "Siap, tunggu sebentar ya aku proses dulu 🙏"
}

var businessWords = regexp.MustCompile(`(?i)\b(restart|reboot|matikan|hidupkan|nyalakan|shutdown|kill|export|absen|generate|buat bast|bikin bast|evidence|status|cek|detail|kenapa|docker|system status|status sistem|status docker|status server)\b`)
var conversationWords = regexp.MustCompile(`(?i)\b(kenalin|kenalan|siapa kamu|siapa nih|siapa sih|kamu siapa|halo|hai conform|hallo|hi conform|assalamualaikum|pagi conform|siang conform|sore conform|malam conform|makasih|terima kasih|thanks|thank you|mantap|keren|bisa ngapain|bisa apa aja|bantuin apa|fungsi kamu|tolong apa)\b`)
var dmFastWords = regexp.MustCompile(`(?i)\b(attendance|absen|absensi|tasklist|task list|kurang|progress|evidence|rebind|ganti nomor|cuti|izin|ijin|sakit)\b`)
var dmNavigation = regexp.MustCompile(`(?i)^(menu|home|kembali|bantuan|help|batal|cancel)$`)
var dmConfirmation = regexp.MustCompile(`(?i)^(ya|iya|yes|y|betul|benar|yoi|bener|bukan|tidak|no|salah|nggak|gak|ga)$`)
var dmClock = regexp.MustCompile(`^(?:[01]?\d|2[0-3])[:.]\d{2}(?:\s+(?:[01]?\d|2[0-3])[:.]\d{2})?$`)
var mentionStrip = regexp.MustCompile(`@[\w.-]+`)

func looksLikeConversation(text string) bool {
	stripped := mentionStrip.ReplaceAllString(text, " ")
	return !businessWords.MatchString(stripped) && conversationWords.MatchString(stripped)
}

func looksLikeDMFastPath(text string) bool {
	stripped := strings.TrimSpace(mentionStrip.ReplaceAllString(text, " "))
	if stripped == "" || regexp.MustCompile(`^\d+$`).MatchString(stripped) || regexp.MustCompile(`(?i)^(pmo:|rebind:)`).MatchString(stripped) || regexp.MustCompile(`^PMO-[A-Za-z0-9_-]+$`).MatchString(stripped) || dmNavigation.MatchString(stripped) || dmConfirmation.MatchString(stripped) || dmClock.MatchString(stripped) || looksLikeConversation(stripped) {
		return true
	}
	return dmFastWords.MatchString(stripped)
}

func safeEqual(left, right string) bool {
	a, b := []byte(left), []byte(right)
	if len(a) == 0 || len(a) != len(b) {
		return false
	}
	return subtle.ConstantTimeCompare(a, b) == 1
}

func configuredToken() string {
	path := os.Getenv("BOT_BRIDGE_TOKEN_FILE")
	if path == "" {
		path = os.Getenv("SYNC_INGEST_TOKEN_FILE")
	}
	if path == "" {
		path = "/run/secrets/sync_ingest_token"
	}
	data, err := os.ReadFile(path)
	if err != nil {
		return ""
	}
	return strings.TrimSpace(string(data))
}

func evidenceExtension(mimetype string) string {
	mt := strings.ToLower(mimetype)
	switch {
	case strings.Contains(mt, "png"):
		return ".png"
	case strings.Contains(mt, "webp"):
		return ".webp"
	case strings.Contains(mt, "pdf"):
		return ".pdf"
	default:
		return ".jpg"
	}
}

func mimeForPath(path string) string {
	switch strings.ToLower(filepath.Ext(path)) {
	case ".pdf":
		return "application/pdf"
	case ".csv":
		return "text/csv"
	case ".png":
		return "image/png"
	case ".jpg", ".jpeg":
		return "image/jpeg"
	default:
		return "application/octet-stream"
	}
}
