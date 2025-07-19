package orders

import (
	"database/sql"
	"lottery/cmd/pkg/db"

	"github.com/gin-gonic/gin"
	slog "github.com/stainton/logger"
)

func GetAllOrdersWrapper(logger slog.Logger, d *sql.DB) gin.HandlerFunc {
	return func(c *gin.Context) {
		orders, err := db.GetAllOrders(d)
		if err != nil {
			logger.Errorf("获取所有的订单失败：%+v", err)
			c.JSON(500, gin.H{"error": "Failed to retrieve orders"})
			return
		}
		c.JSON(200, gin.H{"orders": orders})
	}
}
