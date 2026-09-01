package main

import (
	"os"
	"path/filepath"
	"testing"
)

func TestOperatorActionMarkerSurvivesRuntimeStateRestart(t *testing.T) {
	root := t.TempDir()
	dataDir := filepath.Join(root, "data")
	authDir := filepath.Join(dataDir, "auth-whatsmeow")
	if err := os.MkdirAll(authDir, 0o750); err != nil {
		t.Fatal(err)
	}

	state := newRuntimeState(dataDir, authDir)
	state.requireOperatorAction("logged-out", "401: logged out from another device")
	if !state.operatorActionPending() {
		t.Fatal("expected operator action to be required")
	}
	if got := state.snapshot().Connection; got != "pairing-required" {
		t.Fatalf("got connection %q, want pairing-required", got)
	}

	reloaded := newRuntimeState(dataDir, authDir)
	got := reloaded.snapshot()
	if !got.OperatorActionRequired {
		t.Fatal("expected persisted operator-action marker")
	}
	if got.OperatorReason != "logged-out: 401: logged out from another device" {
		t.Fatalf("unexpected reason %q", got.OperatorReason)
	}
	if got.Connection != "pairing-required" {
		t.Fatalf("got connection %q, want pairing-required", got.Connection)
	}
}

func TestExistingSessionDatabaseStartsWithRecoveryGuard(t *testing.T) {
	root := t.TempDir()
	dataDir := filepath.Join(root, "data")
	authDir := filepath.Join(dataDir, "auth-whatsmeow")
	if err := os.MkdirAll(authDir, 0o750); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(authDir, "session.db"), []byte("existing"), 0o640); err != nil {
		t.Fatal(err)
	}

	state := newRuntimeState(dataDir, authDir)
	got := state.snapshot()
	if !got.OperatorActionRequired {
		t.Fatal("existing session DB should start with recovery guard")
	}
	if got.OperatorReason == "" {
		t.Fatal("recovery guard should explain why pairing is blocked")
	}
}

func TestFreshAuthDirectoryDoesNotRequireOperatorAction(t *testing.T) {
	root := t.TempDir()
	dataDir := filepath.Join(root, "data")
	authDir := filepath.Join(dataDir, "auth-whatsmeow")
	if err := os.MkdirAll(authDir, 0o750); err != nil {
		t.Fatal(err)
	}

	state := newRuntimeState(dataDir, authDir)
	if state.operatorActionPending() {
		t.Fatal("fresh auth directory should allow first-time setup")
	}
}

func TestClearOperatorActionRemovesPersistentMarker(t *testing.T) {
	root := t.TempDir()
	dataDir := filepath.Join(root, "data")
	authDir := filepath.Join(dataDir, "auth-whatsmeow")
	if err := os.MkdirAll(authDir, 0o750); err != nil {
		t.Fatal(err)
	}

	state := newRuntimeState(dataDir, authDir)
	state.requireOperatorAction("logged-out", "401")
	state.clearOperatorAction()

	if state.operatorActionPending() {
		t.Fatal("operator action should be cleared")
	}
	marker := filepath.Join(authDir, "operator-action-required.json")
	if _, err := os.Stat(marker); !os.IsNotExist(err) {
		t.Fatalf("marker still exists: %v", err)
	}
}
