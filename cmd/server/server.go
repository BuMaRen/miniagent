package server

import (
	"database/sql"
	"lottery/cmd/server/schemes"

	"github.com/gin-gonic/gin"
)

func RunServer(addr string) error {
	router := gin.Default()
	var db *sql.DB
	schemes.RegisterHandlers(db, router)
	return router.Run(addr)
}
