package main

import (
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"time"
)

type operatorActionMarker struct {
	Connection string    `json:"connection"`
	Reason     string    `json:"reason"`
	CreatedAt  time.Time `json:"created_at"`
}

func (s *runtimeState) loadOperatorActionMarker() {
	if s.repairMarker == "" {
		return
	}
	data, err := os.ReadFile(s.repairMarker)
	if err != nil {
		return
	}
	var marker operatorActionMarker
	if json.Unmarshal(data, &marker) != nil {
		return
	}
	s.mu.Lock()
	s.operatorActionRequired = true
	s.operatorReason = marker.Reason
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
	s.connection = connection
	s.connectionChangedAt = now
	s.operatorActionRequired = true
	s.operatorReason = reason
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
