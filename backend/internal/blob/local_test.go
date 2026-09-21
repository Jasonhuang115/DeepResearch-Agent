package blob

import (
	"context"
	"os"
	"path/filepath"
	"testing"
)

func TestSessionPrefix(t *testing.T) {
	if got := SessionPrefix("ten_a", "conv_1"); got != "tenants/ten_a/conversations/conv_1/" {
		t.Fatalf("%s", got)
	}
	if got := SessionPrefix("", ""); got != "tenants/default/conversations/default/" {
		t.Fatalf("%s", got)
	}
}

func TestLocalPutGetListDeleteIsolated(t *testing.T) {
	root := t.TempDir()
	store := NewLocal(root)
	ctx := context.Background()
	a := SessionPrefix("ten_a", "conv_a") + "sources/src_03.md"
	b := SessionPrefix("ten_b", "conv_b") + "sources/src_03.md"
	if err := store.Put(ctx, a, []byte("body-a")); err != nil {
		t.Fatal(err)
	}
	if err := store.Put(ctx, b, []byte("body-b")); err != nil {
		t.Fatal(err)
	}
	got, err := store.Get(ctx, a)
	if err != nil || string(got) != "body-a" {
		t.Fatalf("get a: %s %v", got, err)
	}
	listed, err := store.List(ctx, SessionPrefix("ten_a", "conv_a"))
	if err != nil || len(listed) != 1 || listed[0] != a {
		t.Fatalf("list a: %v %v", listed, err)
	}
	if err := store.DeletePrefix(ctx, SessionPrefix("ten_a", "conv_a")); err != nil {
		t.Fatal(err)
	}
	if _, err := store.Get(ctx, a); !os.IsNotExist(err) {
		t.Fatalf("expected missing a, err=%v", err)
	}
	gotB, err := store.Get(ctx, b)
	if err != nil || string(gotB) != "body-b" {
		t.Fatalf("tenant b should remain: %s %v", gotB, err)
	}
	if _, err := os.Stat(filepath.Join(root, "tenants", "ten_b", "conversations", "conv_b", "sources", "src_03.md")); err != nil {
		t.Fatal(err)
	}
}

func TestLocalRejectsEmptyPrefixDelete(t *testing.T) {
	store := NewLocal(t.TempDir())
	if err := store.DeletePrefix(context.Background(), ""); err == nil {
		t.Fatal("expected error")
	}
}
