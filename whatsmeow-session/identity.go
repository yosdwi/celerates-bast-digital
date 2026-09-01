package main

import (
	"context"
	"fmt"

	"go.mau.fi/whatsmeow/store"
	"go.mau.fi/whatsmeow/types"
	"go.mau.fi/whatsmeow/types/events"
)

func canonicalPhoneJID(jid types.JID) (types.JID, bool) {
	if jid.IsEmpty() || jid.Server != types.DefaultUserServer || jid.User == "" {
		return types.EmptyJID, false
	}
	return jid.ToNonAD(), true
}

func canonicalDMIdentity(
	ctx context.Context,
	evt *events.Message,
	lids store.LIDStore,
) (types.JID, error) {
	if evt == nil || evt.Info.IsGroup {
		return types.EmptyJID, fmt.Errorf("canonical DM identity requires a direct message")
	}
	if jid, ok := canonicalPhoneJID(evt.Info.Sender); ok {
		return jid, nil
	}
	if jid, ok := canonicalPhoneJID(evt.Info.SenderAlt); ok {
		return jid, nil
	}
	if jid, ok := canonicalPhoneJID(evt.Info.Chat); ok {
		return jid, nil
	}

	lid := evt.Info.Sender
	if lid.Server != types.HiddenUserServer {
		lid = evt.Info.Chat
	}
	if lid.IsEmpty() || lid.Server != types.HiddenUserServer || lids == nil {
		return types.EmptyJID, fmt.Errorf(
			"no canonical phone JID for sender=%s sender_alt=%s chat=%s",
			evt.Info.Sender,
			evt.Info.SenderAlt,
			evt.Info.Chat,
		)
	}
	pn, err := lids.GetPNForLID(ctx, lid.ToNonAD())
	if err != nil {
		return types.EmptyJID, fmt.Errorf("resolve LID %s to phone JID: %w", lid, err)
	}
	if jid, ok := canonicalPhoneJID(pn); ok {
		return jid, nil
	}
	return types.EmptyJID, fmt.Errorf("no phone mapping stored for LID %s", lid)
}
