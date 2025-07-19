package orders

import (
	"database/sql"
	"lottery/cmd/pkg/db"

	"github.com/gin-gonic/gin"
	slog "github.com/stainton/logger"
)

var ordersTableExists = false

func ordersTableWrapper(logger slog.Logger, d *sql.DB, handler func(slog.Logger, *sql.DB) gin.HandlerFunc) gin.HandlersChain {
	return gin.HandlersChain{
		func(c *gin.Context) {
			if !ordersTableExists {
				err := db.CreateOrdersTable(d)
				if err != nil {
					logger.Errorf("创建orders表失败：%+v", err)
					c.JSON(500, gin.H{"error": err.Error()})
					c.Abort()
					return
				}
				ordersTableExists = true
			}
			c.Next()
		},
		handler(logger, d),
	}
}

func RegisterHandlers(logger slog.Logger, d *sql.DB, router *gin.Engine) {
	router.GET("/orders", ordersTableWrapper(logger, d, GetAllOrdersWrapper)...)
	router.POST("/orders", ordersTableWrapper(logger, d, CreateOrdersWrapper)...)
}
