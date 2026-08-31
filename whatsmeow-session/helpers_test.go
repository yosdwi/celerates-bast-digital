package main

import (
	"strings"
	"testing"
)

func TestInteractiveFallbackAndDigitResolution(t *testing.T) {
	payload := parseInteractiveReply(`{"kind":"interactive","text":"Pilih menu","footer":"Digital BAST","actions":[{"id":"status","label":"Status Saya"},{"id":"attendance","label":"Attendance"}]}`)
	if payload == nil {
		t.Fatal("interactive payload was not parsed")
	}
	text := fallbackText(payload)
	if !strings.Contains(text, "1. Status Saya") || !strings.Contains(text, "2. Attendance") {
		t.Fatalf("unexpected fallback: %q", text)
	}
	menus := newMenuStore()
	menus.remember("6281@s.whatsapp.net", payload.Actions)
	if got := menus.resolve("6281@s.whatsapp.net", "2"); got != "attendance" {
		t.Fatalf("got %q", got)
	}
	menus.forget("6281@s.whatsapp.net")
	if got := menus.resolve("6281@s.whatsapp.net", "2"); got != "2" {
		t.Fatalf("stale menu resolved to %q", got)
	}
}

func TestInteractiveCanDisableDigitShortcuts(t *testing.T) {
	payload := parseInteractiveReply(`{"kind":"interactive","text":"Pilih evidence 1 atau 2","digitShortcuts":false,"actions":[{"id":"cancel","label":"Batal"}]}`)
	if payload == nil {
		t.Fatal("interactive payload was not parsed")
	}
	if digitShortcutsEnabled(payload) {
		t.Fatal("digit shortcuts should be disabled")
	}
	if got := fallbackText(payload); !strings.Contains(got, "• Batal: cancel") {
		t.Fatalf("unexpected fallback: %q", got)
	}
}

func TestFilePayload(t *testing.T) {
	file := parseFileReply(`{"kind":"file","path":"/tmp/report.pdf","filename":"report.pdf","caption":"BAST"}`)
	if file == nil || file.Path != "/tmp/report.pdf" || file.Filename != "report.pdf" {
		t.Fatalf("unexpected file payload: %#v", file)
	}
}

func TestFastPathClassification(t *testing.T) {
	for _, text := range []string{"halo", "menu", "attendance", "1", "07:30", "pmo:attendance:abc:approve"} {
		if !looksLikeDMFastPath(text) {
			t.Errorf("expected fast path for %q", text)
		}
	}
	if looksLikeConversation("generate bast") {
		t.Fatal("business command must not be classified as conversation")
	}
}

func TestValidDirectJID(t *testing.T) {
	if !validDirectJID("628123456789@s.whatsapp.net") {
		t.Fatal("PN JID should be valid")
	}
	if !validDirectJID("123456789@lid") {
		t.Fatal("LID JID should be valid")
	}
	if validDirectJID("120363000000@g.us") {
		t.Fatal("group JID must not be accepted by outbound DM endpoint")
	}
}

func TestEvidenceExtension(t *testing.T) {
	if evidenceExtension("image/png") != ".png" || evidenceExtension("application/pdf") != ".pdf" || evidenceExtension("image/jpeg") != ".jpg" {
		t.Fatal("unexpected evidence extension")
	}
}
