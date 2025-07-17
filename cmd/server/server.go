package server

import (
	"lottery/cmd/server/orders"
	"lottery/cmd/server/schemes"

	"github.com/gin-gonic/gin"
)

func RunServer(cfg *ServerConfig) error {
	router := gin.Default()
	err := cfg.Initialize()
	if err != nil {
		return err
	}
	schemes.RegisterHandlers(cfg.connection, router)
	orders.RegisterHandlers(cfg.connection, router)
	return router.Run(cfg.Addr)
}
