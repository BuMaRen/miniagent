package orders

import (
	"database/sql"
	"lottery/cmd/pkg/db"

	"github.com/gin-gonic/gin"
)

func GetAllOrdersWrapper(d *sql.DB) gin.HandlerFunc {
	return func(c *gin.Context) {
		orders, err := db.GetAllOrders(d)
		if err != nil {
			c.JSON(500, gin.H{"error": "Failed to retrieve orders"})
			return
		}
		c.JSON(200, gin.H{"orders": orders})
	}
}
