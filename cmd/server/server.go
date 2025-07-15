package server

import (
	"lottery/cmd/server/schemes"

	"github.com/gin-gonic/gin"
)

func RunServer(addr string) error {
	router := gin.Default()
	schemes.RegisterHandlers(router)
	return router.Run(addr)
}
