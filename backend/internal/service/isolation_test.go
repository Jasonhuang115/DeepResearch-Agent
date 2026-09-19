package service

import (
	"context"
	"testing"

	"deepresearch/internal/tenant"
)

func TestPrincipalRequired(t *testing.T) {
	if _, err := tenant.FromContext(context.Background()); err == nil {
		t.Fatal("expected missing principal")
	}
	ctx := tenant.WithPrincipal(context.Background(), tenant.Principal{UserID: 1, TenantID: 2})
	p, err := tenant.FromContext(ctx)
	if err != nil || p.TenantID != 2 || p.UserID != 1 {
		t.Fatalf("got %+v err %v", p, err)
	}
}
