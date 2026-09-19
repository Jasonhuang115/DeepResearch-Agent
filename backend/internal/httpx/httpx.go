package httpx

import (
	"errors"
	"net/http"

	"github.com/gin-gonic/gin"
)

type Envelope struct {
	Data any `json:"data,omitempty"`
}

type ErrorBody struct {
	Error ErrorDetail `json:"error"`
}

type ErrorDetail struct {
	Code    string `json:"code"`
	Message string `json:"message"`
}

type APIError struct {
	Status  int
	Code    string
	Message string
}

func (e APIError) Error() string { return e.Message }

func Err(status int, code, msg string) APIError {
	return APIError{Status: status, Code: code, Message: msg}
}

var (
	ErrUnauthorized = Err(http.StatusUnauthorized, "unauthorized", "unauthorized")
	ErrForbidden    = Err(http.StatusForbidden, "forbidden", "forbidden")
	ErrNotFound     = Err(http.StatusNotFound, "not_found", "not found")
	ErrConflict     = Err(http.StatusConflict, "conflict", "conflict")
	ErrValidation   = Err(http.StatusBadRequest, "validation", "invalid request")
	ErrRateLimited  = Err(http.StatusTooManyRequests, "rate_limited", "rate limited")
	ErrInternal     = Err(http.StatusInternalServerError, "internal", "internal error")
)

func OK(c *gin.Context, data any) {
	c.JSON(http.StatusOK, Envelope{Data: data})
}

func Accepted(c *gin.Context, data any) {
	c.JSON(http.StatusAccepted, Envelope{Data: data})
}

func Fail(c *gin.Context, err error) {
	var api APIError
	if errors.As(err, &api) {
		c.JSON(api.Status, ErrorBody{Error: ErrorDetail{Code: api.Code, Message: api.Message}})
		return
	}
	c.JSON(http.StatusInternalServerError, ErrorBody{Error: ErrorDetail{Code: "internal", Message: err.Error()}})
}

func RequestID(c *gin.Context) string {
	if v := c.GetString("request_id"); v != "" {
		return v
	}
	return c.GetHeader("X-Request-Id")
}
