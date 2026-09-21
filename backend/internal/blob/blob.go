package blob

import (
	"context"
	"fmt"
	"strings"
)

type Store interface {
	Put(ctx context.Context, key string, data []byte) error
	Get(ctx context.Context, key string) ([]byte, error)
	List(ctx context.Context, prefix string) ([]string, error)
	DeletePrefix(ctx context.Context, prefix string) error
}

func SessionPrefix(tenantID, conversationID string) string {
	t := safeSeg(tenantID)
	c := safeSeg(conversationID)
	return fmt.Sprintf("tenants/%s/conversations/%s/", t, c)
}

func safeSeg(raw string) string {
	s := strings.TrimSpace(raw)
	if s == "" {
		return "default"
	}
	return s
}
