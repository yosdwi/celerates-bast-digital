package main

import (
	"encoding/json"
	"fmt"

	"go.mau.fi/whatsmeow/proto/waE2E"
)

// messageTextCompat keeps the inbound contract of the previous Baileys
// transport. Outbound menus intentionally remain numbered text for now, but
// users may still tap an older button/list message that is already present in
// their chat, and future isolated transport experiments can reuse the same
// worker action IDs without changing business logic.
func messageTextCompat(msg *waE2E.Message) string {
	if selected := interactiveSelection(msg); selected != "" {
		return selected
	}
	return messageText(msg)
}

func interactiveSelection(msg *waE2E.Message) string {
	if msg == nil {
		return ""
	}
	if response := msg.GetButtonsResponseMessage(); response != nil {
		if selected := response.GetSelectedButtonID(); selected != "" {
			return selected
		}
	}
	if response := msg.GetTemplateButtonReplyMessage(); response != nil {
		if selected := response.GetSelectedID(); selected != "" {
			return selected
		}
	}
	if response := msg.GetListResponseMessage(); response != nil {
		if selected := response.GetSingleSelectReply().GetSelectedRowID(); selected != "" {
			return selected
		}
	}
	if response := msg.GetInteractiveResponseMessage(); response != nil {
		if native := response.GetNativeFlowResponseMessage(); native != nil {
			return nativeFlowSelectionJSON(native.GetParamsJSON())
		}
	}
	return ""
}

func nativeFlowSelectionJSON(raw string) string {
	if raw == "" {
		return ""
	}
	var payload map[string]any
	if err := json.Unmarshal([]byte(raw), &payload); err != nil {
		return ""
	}
	for _, key := range []string{"id", "selectedId", "selected_id", "buttonId", "button_id", "rowId", "row_id"} {
		value, ok := payload[key]
		if !ok || value == nil {
			continue
		}
		switch typed := value.(type) {
		case string:
			if typed != "" {
				return typed
			}
		case json.Number:
			return typed.String()
		case float64:
			return fmt.Sprintf("%v", typed)
		}
	}
	return ""
}
