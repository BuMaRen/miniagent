package orders

import (
	"database/sql"
	"lottery/cmd/pkg/db"
	"lottery/pkg/schemas"

	"github.com/gin-gonic/gin"
)

func CreateOrdersWrapper(d *sql.DB) gin.HandlerFunc {
	return func(c *gin.Context) {
		order := &schemas.NewOrder{}
		if err := c.ShouldBindJSON(order); err != nil {
			c.JSON(400, gin.H{"error": "Invalid input"})
			return
		}

		err := db.CreateOrder(d, order)
		if err != nil {
			c.JSON(500, gin.H{"error": "Failed to create order"})
			return
		}

		c.JSON(201, gin.H{"message": "Order created successfully", "order": order})
	}
}
