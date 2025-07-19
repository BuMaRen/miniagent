package schemes

import (
	"database/sql"
	"lottery/cmd/pkg/db"

	"github.com/gin-gonic/gin"
	slog "github.com/stainton/logger"
)

var schemesTableExists = false

func schemesTableWrapper(logger slog.Logger, d *sql.DB, handler func(slog.Logger, *sql.DB) gin.HandlerFunc) gin.HandlersChain {
	return gin.HandlersChain{
		func(c *gin.Context) {
			if !schemesTableExists {
				err := db.CreateSchemesTable(d)
				if err != nil {
					logger.Errorf("创建schemes表失败：%+v", err)
					c.JSON(500, gin.H{"error": err.Error()})
					c.Abort()
					return
				}
				schemesTableExists = true
			}
			c.Next()
		},
		handler(logger, d),
	}
}

func RegisterHandlers(logger slog.Logger, d *sql.DB, router *gin.Engine) {
	router.GET("/schemes", schemesTableWrapper(logger, d, GetAllSchemesWrapper)...)
	router.POST("/schemes", schemesTableWrapper(logger, d, CreateSchemeWrapper)...)
	router.DELETE("/schemes/:id", schemesTableWrapper(logger, d, DeleteSchemeWrapper)...)
}
