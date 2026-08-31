package main

import (
	"testing"

	"go.mau.fi/whatsmeow/proto/waE2E"
	"google.golang.org/protobuf/proto"
)

func TestInteractiveSelectionCompatibility(t *testing.T) {
	tests := []struct {
		name string
		msg  *waE2E.Message
		want string
	}{
		{
			name: "legacy button",
			msg: &waE2E.Message{ButtonsResponseMessage: &waE2E.ButtonsResponseMessage{
				SelectedButtonID: proto.String("attendance"),
			}},
			want: "attendance",
		},
		{
			name: "template button",
			msg: &waE2E.Message{TemplateButtonReplyMessage: &waE2E.TemplateButtonReplyMessage{
				SelectedID: proto.String("status"),
			}},
			want: "status",
		},
		{
			name: "list row",
			msg: &waE2E.Message{ListResponseMessage: &waE2E.ListResponseMessage{
				SingleSelectReply: &waE2E.ListResponseMessage_SingleSelectReply{SelectedRowID: proto.String("task-evidence")},
			}},
			want: "task-evidence",
		},
		{
			name: "native flow",
			msg: &waE2E.Message{InteractiveResponseMessage: &waE2E.InteractiveResponseMessage{
				InteractiveResponseMessage: &waE2E.InteractiveResponseMessage_NativeFlowResponseMessage_{
					NativeFlowResponseMessage: &waE2E.InteractiveResponseMessage_NativeFlowResponseMessage{
						ParamsJSON: proto.String(`{"selected_id":"pmo:attendance:123:approve"}`),
					},
				},
			}},
			want: "pmo:attendance:123:approve",
		},
	}
	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			if got := interactiveSelection(tc.msg); got != tc.want {
				t.Fatalf("got %q, want %q", got, tc.want)
			}
		})
	}
}

func TestMessageTextCompatFallsBackToPlainText(t *testing.T) {
	msg := &waE2E.Message{Conversation: proto.String("halo")}
	if got := messageTextCompat(msg); got != "halo" {
		t.Fatalf("got %q", got)
	}
}

func TestNativeFlowSelectionJSONRejectsMalformedInput(t *testing.T) {
	if got := nativeFlowSelectionJSON("not-json"); got != "" {
		t.Fatalf("malformed native flow resolved to %q", got)
	}
}
