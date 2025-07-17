package orders

import (
	"database/sql"

	"github.com/gin-gonic/gin"
)

func RegisterHandlers(db *sql.DB, router *gin.Engine) {
	router.GET("/orders", GetAllOrdersWrapper(db))
	router.POST("/orders", CreateOrdersWrapper(db))
}
