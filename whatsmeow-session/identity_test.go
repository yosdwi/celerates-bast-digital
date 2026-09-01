package main

import (
	"context"
	"errors"
	"testing"

	"go.mau.fi/whatsmeow/store"
	"go.mau.fi/whatsmeow/types"
	"go.mau.fi/whatsmeow/types/events"
)

type fakeLIDStore struct {
	pn  types.JID
	err error
}

func (f *fakeLIDStore) PutManyLIDMappings(context.Context, []store.LIDMapping) error { return nil }
func (f *fakeLIDStore) PutLIDMapping(context.Context, types.JID, types.JID) error    { return nil }
func (f *fakeLIDStore) GetPNForLID(context.Context, types.JID) (types.JID, error) {
	return f.pn, f.err
}
func (f *fakeLIDStore) GetLIDForPN(context.Context, types.JID) (types.JID, error) {
	return types.EmptyJID, nil
}
func (f *fakeLIDStore) GetManyLIDsForPNs(context.Context, []types.JID) (map[types.JID]types.JID, error) {
	return nil, nil
}

func jid(user, server string) types.JID {
	return types.NewJID(user, server)
}

func directEvent(chat, sender, senderAlt types.JID) *events.Message {
	return &events.Message{Info: types.MessageInfo{MessageSource: types.MessageSource{
		Chat: chat, Sender: sender, SenderAlt: senderAlt,
	}}}
}

func TestCanonicalDMIdentityKeepsPhoneJID(t *testing.T) {
	pn := jid("6281234567890", types.DefaultUserServer)
	got, err := canonicalDMIdentity(context.Background(), directEvent(pn, pn, types.EmptyJID), &fakeLIDStore{})
	if err != nil {
		t.Fatalf("canonicalDMIdentity returned error: %v", err)
	}
	if got != pn {
		t.Fatalf("got %s, want %s", got, pn)
	}
}

func TestCanonicalDMIdentityPrefersSenderAltPhoneForLID(t *testing.T) {
	lid := jid("253699456815126", types.HiddenUserServer)
	pn := jid("6281234567890", types.DefaultUserServer)
	got, err := canonicalDMIdentity(context.Background(), directEvent(lid, lid, pn), &fakeLIDStore{})
	if err != nil {
		t.Fatalf("canonicalDMIdentity returned error: %v", err)
	}
	if got != pn {
		t.Fatalf("got %s, want %s", got, pn)
	}
}

func TestCanonicalDMIdentityFallsBackToStoredLIDMapping(t *testing.T) {
	lid := jid("253699456815126", types.HiddenUserServer)
	pn := jid("6281234567890", types.DefaultUserServer)
	got, err := canonicalDMIdentity(
		context.Background(),
		directEvent(lid, lid, types.EmptyJID),
		&fakeLIDStore{pn: pn},
	)
	if err != nil {
		t.Fatalf("canonicalDMIdentity returned error: %v", err)
	}
	if got != pn {
		t.Fatalf("got %s, want %s", got, pn)
	}
}

func TestCanonicalDMIdentityFailsClosedWhenLIDCannotResolve(t *testing.T) {
	lid := jid("253699456815126", types.HiddenUserServer)
	_, err := canonicalDMIdentity(
		context.Background(),
		directEvent(lid, lid, types.EmptyJID),
		&fakeLIDStore{err: errors.New("lookup failed")},
	)
	if err == nil {
		t.Fatal("expected unresolved LID to fail closed")
	}
}
