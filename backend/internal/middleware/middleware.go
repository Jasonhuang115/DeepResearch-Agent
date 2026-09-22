package middleware

import (
	"log/slog"
	"net/http"
	"strings"
	"time"

	"github.com/gin-gonic/gin"

	"deepresearch/internal/cache"
	"deepresearch/internal/httpx"
	"deepresearch/internal/id"
	"deepresearch/internal/service"
	"deepresearch/internal/tenant"
)

func RequestID() gin.HandlerFunc {
	return func(c *gin.Context) {
		rid := c.GetHeader("X-Request-Id")
		if rid == "" {
			rid = id.New("req_")
		}
		c.Set("request_id", rid)
		c.Header("X-Request-Id", rid)
		c.Next()
	}
}

func Recover() gin.HandlerFunc {
	return func(c *gin.Context) {
		defer func() {
			if rec := recover(); rec != nil {
				slog.Error("panic", "err", rec, "request_id", c.GetString("request_id"))
				httpx.Fail(c, httpx.ErrInternal)
				c.Abort()
			}
		}()
		c.Next()
	}
}

func CORS(origins []string) gin.HandlerFunc {
	allow := map[string]bool{}
	for _, o := range origins {
		allow[o] = true
	}
	return func(c *gin.Context) {
		origin := c.GetHeader("Origin")
		if allow[origin] {
			c.Header("Access-Control-Allow-Origin", origin)
			c.Header("Access-Control-Allow-Credentials", "true")
			c.Header("Access-Control-Allow-Headers", "Authorization, Content-Type, Idempotency-Key, Last-Event-ID, X-Request-Id")
			c.Header("Access-Control-Allow-Methods", "GET, POST, PATCH, DELETE, OPTIONS")
			c.Header("Access-Control-Expose-Headers", "X-Request-Id")
		}
		if c.Request.Method == http.MethodOptions {
			c.AbortWithStatus(http.StatusNoContent)
			return
		}
		c.Next()
	}
}

func Auth(auth *service.Auth) gin.HandlerFunc {
	return func(c *gin.Context) {
		h := c.GetHeader("Authorization")
		if !strings.HasPrefix(h, "Bearer ") {
			httpx.Fail(c, httpx.ErrUnauthorized)
			c.Abort()
			return
		}
		u, ten, err := auth.ParseAccess(strings.TrimPrefix(h, "Bearer "))
		if err != nil {
			httpx.Fail(c, httpx.ErrUnauthorized)
			c.Abort()
			return
		}
		p := tenant.Principal{
			UserID: u.ID, TenantID: ten.ID,
			UserPublic: u.PublicID, TenantPublic: ten.PublicID,
			Role: u.Role,
		}
		ctx := tenant.WithPrincipal(c.Request.Context(), p)
		c.Request = c.Request.WithContext(ctx)
		c.Set("principal", p)
		c.Next()
	}
}

func RateLimit(r *cache.Redis, perMin int) gin.HandlerFunc {
	return func(c *gin.Context) {
		switch c.Request.Method {
		case http.MethodGet, http.MethodHead, http.MethodOptions:
			c.Next()
			return
		}
		p, err := tenant.FromContext(c.Request.Context())
		if err != nil {
			c.Next()
			return
		}
		n, err := r.IncrWindow(c.Request.Context(), "rl:"+itoa(p.TenantID), time.Minute)
		if err != nil {
			c.Next()
			return
		}
		if n > int64(perMin) {
			httpx.Fail(c, httpx.ErrRateLimited)
			c.Abort()
			return
		}
		c.Next()
	}
}

func itoa(n int64) string {
	if n == 0 {
		return "0"
	}
	var b [20]byte
	i := len(b)
	for n > 0 {
		i--
		b[i] = byte('0' + n%10)
		n /= 10
	}
	return string(b[i:])
}
