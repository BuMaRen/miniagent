package cmd

import (
	"context"
	"sync"

	"github.com/gin-gonic/gin"
)

func StartWeek1Server() {
	server := gin.Default()
	var sMap sync.Map
	root := context.Background()
	server.POST("/start_task", NewStartTaskHandler(root, &sMap))
	server.POST("/stop_task", NewStopTaskHandler(&sMap))
	server.Run("192.168.50.11:9090")
}
