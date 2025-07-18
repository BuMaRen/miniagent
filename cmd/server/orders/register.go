package orders

import (
	"database/sql"
	"lottery/cmd/pkg/db"

	"github.com/gin-gonic/gin"
)

var ordersTableExists = false

func ordersTableWrapper(d *sql.DB, handler func(*sql.DB) gin.HandlerFunc) gin.HandlersChain {
	return gin.HandlersChain{
		func(c *gin.Context) {
			if !ordersTableExists {
				err := db.CreateOrdersTable(d)
				if err != nil {
					c.JSON(500, gin.H{"error": err.Error()})
					c.Abort()
					return
				}
				ordersTableExists = true
			}
			c.Next()
		},
		handler(d),
	}
}

func RegisterHandlers(d *sql.DB, router *gin.Engine) {
	router.GET("/orders", ordersTableWrapper(d, GetAllOrdersWrapper)...)
	router.POST("/orders", ordersTableWrapper(d, CreateOrdersWrapper)...)
}
