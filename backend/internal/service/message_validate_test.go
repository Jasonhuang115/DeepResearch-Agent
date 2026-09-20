package service

import "testing"

func TestValidateMessage(t *testing.T) {
	if err := validateMessage("", 0); err == nil {
		t.Fatal("expected error when empty")
	}
	if err := validateMessage("", 1); err != nil {
		t.Fatal(err)
	}
	if err := validateMessage("hello", 0); err != nil {
		t.Fatal(err)
	}
	long := stringsRepeat("x", 32001)
	if err := validateMessage(long, 0); err == nil {
		t.Fatal("expected too long")
	}
}

func stringsRepeat(s string, n int) string {
	b := make([]byte, 0, n*len(s))
	for i := 0; i < n; i++ {
		b = append(b, s...)
	}
	return string(b)
}
