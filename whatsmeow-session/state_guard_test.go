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

	reloaded := newRuntimeState(dataDir, authDir)
	got := reloaded.snapshot()
	if !got.OperatorActionRequired {
		t.Fatal("expected persisted operator-action marker")
	}
	if got.OperatorReason != "401: logged out from another device" {
		t.Fatalf("unexpected reason %q", got.OperatorReason)
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
