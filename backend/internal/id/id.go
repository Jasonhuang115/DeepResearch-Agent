package id

import (
	"crypto/rand"
	"strings"

	"github.com/oklog/ulid/v2"
)

func New(prefix string) string {
	return prefix + ulid.Make().String()
}

func RandomToken() string {
	var b [32]byte
	_, _ = rand.Read(b[:])
	return ulid.Make().String() + strings.ToLower(encode(b[:]))
}

func encode(b []byte) string {
	const hex = "0123456789abcdef"
	out := make([]byte, len(b)*2)
	for i, v := range b {
		out[i*2] = hex[v>>4]
		out[i*2+1] = hex[v&0x0f]
	}
	return string(out)
}
