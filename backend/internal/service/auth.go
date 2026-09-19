package service

import (
	"context"
	"strings"
	"time"

	"github.com/golang-jwt/jwt/v5"
	"golang.org/x/crypto/bcrypt"

	"deepresearch/internal/cache"
	"deepresearch/internal/config"
	"deepresearch/internal/httpx"
	"deepresearch/internal/id"
	"deepresearch/internal/model"
	"deepresearch/internal/repo"
)

type Auth struct {
	Repo  *repo.Repo
	Redis *cache.Redis
	Cfg   config.Config
}

type TokenPair struct {
	AccessToken  string   `json:"access_token"`
	RefreshToken string   `json:"refresh_token"`
	ExpiresIn    int64    `json:"expires_in"`
	User         UserView `json:"user"`
}

type UserView struct {
	ID          string `json:"id"`
	Email       string `json:"email"`
	DisplayName string `json:"display_name"`
	TenantID    string `json:"tenant_id"`
}

type claims struct {
	TenantID int64  `json:"tidn"`
	UserPub  string `json:"upd"`
	TenPub   string `json:"tpd"`
	Role     string `json:"role"`
	jwt.RegisteredClaims
}

func (a *Auth) Register(ctx context.Context, email, password, name string) (*TokenPair, error) {
	email = strings.ToLower(strings.TrimSpace(email))
	if email == "" || len(password) < 8 || strings.TrimSpace(name) == "" {
		return nil, httpx.ErrValidation
	}
	existing, err := a.Repo.UserByEmail(ctx, email)
	if err != nil {
		return nil, err
	}
	if existing != nil {
		return nil, httpx.Err(409, "conflict", "email already registered")
	}
	hash, err := bcrypt.GenerateFromPassword([]byte(password), bcrypt.DefaultCost)
	if err != nil {
		return nil, err
	}
	ten := &model.Tenant{PublicID: id.New("ten_"), Name: name + "'s workspace"}
	if err := a.Repo.CreateTenant(ctx, ten); err != nil {
		return nil, err
	}
	u := &model.User{
		PublicID:     id.New("usr_"),
		TenantID:     ten.ID,
		Email:        email,
		DisplayName:  name,
		PasswordHash: string(hash),
		Role:         "owner",
	}
	if err := a.Repo.CreateUser(ctx, u); err != nil {
		return nil, err
	}
	return a.issue(ctx, u, ten)
}

func (a *Auth) Login(ctx context.Context, email, password string) (*TokenPair, error) {
	email = strings.ToLower(strings.TrimSpace(email))
	u, err := a.Repo.UserByEmail(ctx, email)
	if err != nil {
		return nil, err
	}
	if u == nil || bcrypt.CompareHashAndPassword([]byte(u.PasswordHash), []byte(password)) != nil {
		return nil, httpx.Err(401, "unauthorized", "invalid credentials")
	}
	ten, err := a.Repo.TenantByID(ctx, u.TenantID)
	if err != nil || ten == nil {
		return nil, httpx.ErrInternal
	}
	return a.issue(ctx, u, ten)
}

func (a *Auth) Refresh(ctx context.Context, token string) (*TokenPair, error) {
	var uid int64
	ok, err := a.Redis.GetJSON(ctx, "refresh:"+token, &uid)
	if err != nil || !ok {
		return nil, httpx.ErrUnauthorized
	}
	_ = a.Redis.Del(ctx, "refresh:"+token)
	u, err := a.Repo.UserByID(ctx, uid)
	if err != nil || u == nil {
		return nil, httpx.ErrUnauthorized
	}
	ten, err := a.Repo.TenantByID(ctx, u.TenantID)
	if err != nil || ten == nil {
		return nil, httpx.ErrUnauthorized
	}
	return a.issue(ctx, u, ten)
}

func (a *Auth) Logout(ctx context.Context, token string) {
	if token != "" {
		_ = a.Redis.Del(ctx, "refresh:"+token)
	}
}

func (a *Auth) ParseAccess(token string) (*model.User, *model.Tenant, error) {
	parsed, err := jwt.ParseWithClaims(token, &claims{}, func(t *jwt.Token) (any, error) {
		return []byte(a.Cfg.JWTSecret), nil
	})
	if err != nil || !parsed.Valid {
		return nil, nil, httpx.ErrUnauthorized
	}
	c, ok := parsed.Claims.(*claims)
	if !ok {
		return nil, nil, httpx.ErrUnauthorized
	}
	uid := int64(0)
	if c.Subject != "" {
		// subject is numeric user id
		for _, ch := range c.Subject {
			if ch < '0' || ch > '9' {
				return nil, nil, httpx.ErrUnauthorized
			}
			uid = uid*10 + int64(ch-'0')
		}
	}
	u := &model.User{ID: uid, PublicID: c.UserPub, TenantID: c.TenantID, Role: c.Role}
	t := &model.Tenant{ID: c.TenantID, PublicID: c.TenPub}
	return u, t, nil
}

func (a *Auth) issue(ctx context.Context, u *model.User, ten *model.Tenant) (*TokenPair, error) {
	now := time.Now()
	exp := now.Add(a.Cfg.AccessTTL)
	tok := jwt.NewWithClaims(jwt.SigningMethodHS256, claims{
		TenantID: ten.ID,
		UserPub:  u.PublicID,
		TenPub:   ten.PublicID,
		Role:     u.Role,
		RegisteredClaims: jwt.RegisteredClaims{
			Subject:   itoa(u.ID),
			ExpiresAt: jwt.NewNumericDate(exp),
			IssuedAt:  jwt.NewNumericDate(now),
		},
	})
	access, err := tok.SignedString([]byte(a.Cfg.JWTSecret))
	if err != nil {
		return nil, err
	}
	refresh := id.RandomToken()
	if err := a.Redis.SetJSON(ctx, "refresh:"+refresh, u.ID, a.Cfg.RefreshTTL); err != nil {
		// Redis down: still return access; refresh will fail later
		refresh = ""
	}
	return &TokenPair{
		AccessToken:  access,
		RefreshToken: refresh,
		ExpiresIn:    int64(a.Cfg.AccessTTL.Seconds()),
		User: UserView{
			ID:          u.PublicID,
			Email:       u.Email,
			DisplayName: u.DisplayName,
			TenantID:    ten.PublicID,
		},
	}, nil
}

func itoa(n int64) string {
	if n == 0 {
		return "0"
	}
	var b [20]byte
	i := len(b)
	neg := n < 0
	if neg {
		n = -n
	}
	for n > 0 {
		i--
		b[i] = byte('0' + n%10)
		n /= 10
	}
	if neg {
		i--
		b[i] = '-'
	}
	return string(b[i:])
}
