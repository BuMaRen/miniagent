package cmd

import (
	"context"
	"fmt"
	"sync"
	"time"
	"week1/api"

	"github.com/gin-gonic/gin"
)

func NewStartTaskHandler(root context.Context, sm *sync.Map) gin.HandlerFunc {
	return func(ctx *gin.Context) {
		StartTaskWithContext(root, ctx, sm)
	}
}

func StartTaskWithContext(root context.Context, c *gin.Context, sm *sync.Map) {
	req := api.TaskReq{}
	if err := c.ShouldBindJSON(&req); err != nil {
		fmt.Println("unmarshal failed")
		c.JSON(400, gin.H{"error": err.Error()})
		return
	}
	c.JSON(200, gin.H{"error": nil})

	ctx, cancel := context.WithTimeout(root, time.Duration(req.TimeOut)*time.Second)
	sm.Store(req.TaskId, cancel)
	go func() {
		defer func() {
			cancel()
			sm.Delete(req.TaskId)
		}()
		for i := 0; i < req.SleepTime; i++ {
			select {
			case <-ctx.Done():
				fmt.Printf("[%v-%v]任务结束, 已运行%v/%v\n", req.TaskId, req.TaskName, i, req.SleepTime)
				return
			default:
				time.Sleep(time.Second)
				// Simulate task work
			}
			if i == req.SleepTime-1 {
				fmt.Printf("[%v-%v]任务完成\n", req.TaskId, req.TaskName)
			}
		}
	}()
}
