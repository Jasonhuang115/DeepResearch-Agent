package cache

import (
	"context"
	"encoding/json"
	"errors"
	"strconv"
	"time"

	"github.com/redis/go-redis/v9"
)

type Redis struct {
	C *redis.Client
}

func Open(addr string) *Redis {
	return &Redis{C: redis.NewClient(&redis.Options{Addr: addr})}
}

func (r *Redis) Ping(ctx context.Context) error {
	return r.C.Ping(ctx).Err()
}

func (r *Redis) SetJSON(ctx context.Context, key string, v any, ttl time.Duration) error {
	b, err := json.Marshal(v)
	if err != nil {
		return err
	}
	return r.C.Set(ctx, key, b, ttl).Err()
}

func (r *Redis) GetJSON(ctx context.Context, key string, dest any) (bool, error) {
	s, err := r.C.Get(ctx, key).Bytes()
	if errors.Is(err, redis.Nil) {
		return false, nil
	}
	if err != nil {
		return false, err
	}
	return true, json.Unmarshal(s, dest)
}

func (r *Redis) SetNXJSON(ctx context.Context, key string, v any, ttl time.Duration) (bool, error) {
	b, err := json.Marshal(v)
	if err != nil {
		return false, err
	}
	return r.C.SetNX(ctx, key, b, ttl).Result()
}

func (r *Redis) Del(ctx context.Context, key string) error {
	return r.C.Del(ctx, key).Err()
}

func (r *Redis) IncrWindow(ctx context.Context, key string, window time.Duration) (int64, error) {
	sec := int64(window / time.Second)
	if sec < 1 {
		sec = 1
	}
	// Bucket by the window so a busy client cannot keep one counter alive forever.
	k := key + ":" + strconv.FormatInt(time.Now().Unix()/sec, 10)
	pipe := r.C.TxPipeline()
	incr := pipe.Incr(ctx, k)
	pipe.Expire(ctx, k, time.Duration(sec)*time.Second+time.Second)
	_, err := pipe.Exec(ctx)
	if err != nil {
		return 0, err
	}
	return incr.Val(), nil
}
