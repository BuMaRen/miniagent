package cmd

import (
	"context"
	"errors"
	"sync"
	"week1/api"

	"github.com/gin-gonic/gin"
)

func NewStopTaskHandler(sm *sync.Map) gin.HandlerFunc {
	return func(ctx *gin.Context) {
		StopTaskHandler(ctx, sm)
	}
}

func StopTaskHandler(c *gin.Context, sm *sync.Map) {
	req := api.StopTaskReq{}
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(400, gin.H{"error": err.Error()})
		return
	}
	c.JSON(200, gin.H{"error": nil})
	value, ok := sm.Load(req.TaskId)
	if !ok {
		return
	}
	values, ok := value.(context.CancelFunc)
	if !ok {
		c.JSON(404, gin.H{"error": errors.New("task not found")})
		return
	}
	values()
	sm.Delete(req.TaskId)
}
