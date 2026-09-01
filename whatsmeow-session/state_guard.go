package main

import (
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"time"
)

type operatorActionMarker struct {
	Connection string    `json:"connection"`
	Reason     string    `json:"reason"`
	CreatedAt  time.Time `json:"created_at"`
}

func operatorReason(connection, reason string) string {
	connection = strings.TrimSpace(connection)
	reason = strings.TrimSpace(reason)
	if connection == "" {
		return reason
	}
	if reason == "" {
		return connection
	}
	return connection + ": " + reason
}

func (s *runtimeState) loadOperatorActionMarker() {
	if s.repairMarker == "" {
		return
	}
	data, err := os.ReadFile(s.repairMarker)
	if err != nil {
		// A fresh first start has no session.db yet, so it may enter normal
		// pairing. If a session DB already exists, however, startup is a
		// recovery path. Keep a temporary guard until GetFirstDevice proves an
		// existing device is still present and Connected clears it. If the
		// device row was removed by a prior permanent logout, main() sees this
		// guard and refuses to auto-start a new QR/pairing-code cycle.
		sessionDB := filepath.Join(filepath.Dir(s.repairMarker), "session.db")
		if _, statErr := os.Stat(sessionDB); statErr == nil {
			s.mu.Lock()
			s.operatorActionRequired = true
			s.operatorReason = "existing-session: prior WhatsApp session store found; do not auto-pair if its device identity is gone"
			s.mu.Unlock()
		}
		return
	}
	var marker operatorActionMarker
	if json.Unmarshal(data, &marker) != nil {
		return
	}
	s.mu.Lock()
	s.connection = "pairing-required"
	s.connectionChangedAt = time.Now().UTC()
	s.operatorActionRequired = true
	s.operatorReason = operatorReason(marker.Connection, marker.Reason)
	s.mu.Unlock()
}

func (s *runtimeState) requireOperatorAction(connection, reason string) {
	now := time.Now().UTC()
	marker := operatorActionMarker{Connection: connection, Reason: reason, CreatedAt: now}
	if s.repairMarker != "" {
		if data, err := json.MarshalIndent(marker, "", "  "); err == nil {
			_ = os.MkdirAll(filepath.Dir(s.repairMarker), 0o750)
			_ = os.WriteFile(s.repairMarker, data, 0o640)
		}
	}
	s.mu.Lock()
	// The connection event remains preserved in the marker and reason, while
	// the runtime state becomes explicitly actionable. This makes controlled
	// pairing available immediately after a permanent logout without needing
	// a container restart just to reveal the recovery control.
	s.connection = "pairing-required"
	s.connectionChangedAt = now
	s.operatorActionRequired = true
	s.operatorReason = operatorReason(connection, reason)
	s.mu.Unlock()
}

func (s *runtimeState) clearOperatorAction() {
	if s.repairMarker != "" {
		err := os.Remove(s.repairMarker)
		if err != nil && !errors.Is(err, os.ErrNotExist) {
			s.logf("failed to clear operator-action marker: %v", err)
		}
	}
	s.mu.Lock()
	s.operatorActionRequired = false
	s.operatorReason = ""
	s.mu.Unlock()
}

func (s *runtimeState) operatorActionPending() bool {
	s.mu.RLock()
	defer s.mu.RUnlock()
	return s.operatorActionRequired
}
