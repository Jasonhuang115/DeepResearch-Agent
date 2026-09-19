package id

import (
	"strings"
	"testing"
)

func TestNewPrefix(t *testing.T) {
	got := New("conv_")
	if !strings.HasPrefix(got, "conv_") {
		t.Fatalf("prefix: %s", got)
	}
	if len(got) < 20 {
		t.Fatalf("too short: %s", got)
	}
}
