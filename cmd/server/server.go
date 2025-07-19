package server

import (
	"context"
	"fmt"
	"lottery/cmd/server/orders"
	"lottery/cmd/server/results"
	"lottery/cmd/server/schemes"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/gin-gonic/gin"
	slog "github.com/stainton/logger"
)

// TODO: 将gin的日志导出到我的日志文件里面
func RunServer(cfg *ServerConfig) {
	ctx, cancel := context.WithCancel(context.Background())
	slogger, stopCh := slog.NewLogger(ctx, cfg.LoggerOptions)
	err := cfg.Initialize()
	if err != nil {
		slogger.Errorf("配置初始化失败，logger准备退出")
		cancel()
		<-stopCh
		fmt.Println("logger finished")
		return
	}
	router := gin.Default()
	schemes.RegisterHandlers(slogger, cfg.connection, router)
	orders.RegisterHandlers(slogger, cfg.connection, router)
	results.RegisterHandler(slogger, cfg.connection, router)
	runserver(router, slogger, cfg)
	cancel()
	fmt.Println("waitting logger finished")
	<-stopCh
	fmt.Println("logger finished")
}

func runserver(engine *gin.Engine, logger slog.Logger, cfg *ServerConfig) {
	srv := &http.Server{
		Addr:    cfg.Addr,
		Handler: engine,
	}

	errChan := make(chan error, 1)
	go func() {
		if err := srv.ListenAndServe(); err != http.ErrServerClosed {
			logger.Errorf("listen: %s\n", err)
			errChan <- err
		}
	}()
	logger.Debugf("Server started")
	quit := make(chan os.Signal, 1)
	signal.Notify(quit, syscall.SIGINT, syscall.SIGTERM)

	select {
	case sig, ok := <-quit:
		fmt.Println(sig, ok)
		logger.Infof("Shutdown Server ...")
	case err := <-errChan:
		logger.Errorf("服务器启动失败：%+v", err)
	}

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	if err := srv.Shutdown(ctx); err != nil {
		logger.Fatalf("Server Shutdown：%+v", err)
	}
}
