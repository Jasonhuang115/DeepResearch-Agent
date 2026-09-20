package api

import (
	"github.com/gin-gonic/gin"
	"github.com/prometheus/client_golang/prometheus/promhttp"

	"deepresearch/internal/cache"
	"deepresearch/internal/config"
	"deepresearch/internal/middleware"
	"deepresearch/internal/service"
	"deepresearch/internal/sse"
)

type Deps struct {
	Cfg    config.Config
	Auth   *service.Auth
	Conv   *service.Conversations
	Redis  *cache.Redis
	Hub    *sse.Hub
}

func Router(d Deps) *gin.Engine {
	gin.SetMode(gin.ReleaseMode)
	r := gin.New()
	maxMem := d.Cfg.UploadMaxBytes * int64(d.Cfg.UploadMaxFiles)
	if maxMem < 32<<20 {
		maxMem = 32 << 20
	}
	r.MaxMultipartMemory = maxMem
	r.Use(middleware.Recover(), middleware.RequestID(), middleware.CORS(d.Cfg.CORSOrigins))
	r.GET("/healthz", func(c *gin.Context) { c.String(200, "ok") })
	r.GET("/metrics", gin.WrapH(promhttp.Handler()))

	h := &Handlers{Auth: d.Auth, Conv: d.Conv, Redis: d.Redis, Hub: d.Hub}

	v1 := r.Group("/v1")
	v1.POST("/auth/register", h.Register)
	v1.POST("/auth/login", h.Login)
	v1.POST("/auth/refresh", h.Refresh)
	v1.POST("/auth/logout", h.Logout)

	authed := v1.Group("")
	authed.Use(middleware.Auth(d.Auth), middleware.RateLimit(d.Redis, d.Cfg.RateLimitPerMinute))
	authed.GET("/auth/me", h.Me)
	authed.GET("/conversations", h.ListConversations)
	authed.POST("/conversations", h.CreateConversation)
	authed.GET("/conversations/:id", h.GetConversation)
	authed.PATCH("/conversations/:id", h.PatchConversation)
	authed.DELETE("/conversations/:id", h.DeleteConversation)
	authed.GET("/conversations/:id/messages", h.ListMessages)
	authed.POST("/conversations/:id/messages", h.PostMessage)
	authed.GET("/runs/:id", h.GetRun)
	authed.POST("/runs/:id/cancel", h.CancelRun)
	authed.GET("/runs/:id/events", h.ListEvents)
	authed.GET("/streams/run/:id", h.StreamRun)
	authed.GET("/streams/conversation/:id", h.StreamConversation)
	return r
}
