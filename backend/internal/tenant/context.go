package tenant

import (
	"context"
	"errors"
)

type ctxKey int

const (
	principalKey ctxKey = iota
	systemKey
)

type Principal struct {
	UserID       int64
	TenantID     int64
	UserPublic   string
	TenantPublic string
	Role         string
}

func WithPrincipal(ctx context.Context, p Principal) context.Context {
	return context.WithValue(ctx, principalKey, p)
}

func FromContext(ctx context.Context) (Principal, error) {
	p, ok := ctx.Value(principalKey).(Principal)
	if !ok || p.UserID == 0 {
		return Principal{}, errors.New("auth context not set")
	}
	return p, nil
}

func MustFrom(ctx context.Context) Principal {
	p, err := FromContext(ctx)
	if err != nil {
		panic(err)
	}
	return p
}

func WithSystem(ctx context.Context) context.Context {
	return context.WithValue(ctx, systemKey, true)
}

func IsSystem(ctx context.Context) bool {
	v, _ := ctx.Value(systemKey).(bool)
	return v
}
