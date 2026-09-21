package service

import (
	"context"
	"os"
	"testing"

	"deepresearch/internal/blob"
	"deepresearch/internal/repo"
	"deepresearch/internal/tenant"
)

func TestPruneSessionsDeletesIdlePrefixOnly(t *testing.T) {
	root := t.TempDir()
	store := blob.NewLocal(root)
	ctx := context.Background()
	a := blob.SessionPrefix("ten_a", "conv_old") + "sources/src_03.md"
	b := blob.SessionPrefix("ten_b", "conv_keep") + "sources/src_03.md"
	if err := store.Put(ctx, a, []byte("old")); err != nil {
		t.Fatal(err)
	}
	if err := store.Put(ctx, b, []byte("keep")); err != nil {
		t.Fatal(err)
	}
	n := PruneSessions(ctx, store, []repo.IdleConversation{
		{TenantPublic: "ten_a", ConversationPublic: "conv_old"},
	})
	if n != 1 {
		t.Fatalf("n=%d", n)
	}
	if _, err := store.Get(ctx, a); !os.IsNotExist(err) {
		t.Fatalf("expected deleted, err=%v", err)
	}
	got, err := store.Get(ctx, b)
	if err != nil || string(got) != "keep" {
		t.Fatalf("keep %s %v", got, err)
	}
}

func TestDeleteConversationPrefix(t *testing.T) {
	root := t.TempDir()
	store := blob.NewLocal(root)
	ctx := tenant.WithPrincipal(context.Background(), tenant.Principal{
		UserID: 1, TenantID: 9, TenantPublic: "ten_a",
	})
	key := blob.SessionPrefix("ten_a", "conv_1") + "tool-output/x.txt"
	other := blob.SessionPrefix("ten_a", "conv_2") + "tool-output/x.txt"
	if err := store.Put(ctx, key, []byte("gone")); err != nil {
		t.Fatal(err)
	}
	if err := store.Put(ctx, other, []byte("stay")); err != nil {
		t.Fatal(err)
	}
	s := &Conversations{Blob: store}
	s.deleteWorkspacePrefix(ctx, "conv_1")
	if _, err := store.Get(ctx, key); !os.IsNotExist(err) {
		t.Fatalf("conv_1 should be gone: %v", err)
	}
	got, err := store.Get(ctx, other)
	if err != nil || string(got) != "stay" {
		t.Fatalf("conv_2 %s %v", got, err)
	}
}
