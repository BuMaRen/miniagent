package schemes

import (
	"database/sql"
	"lottery/cmd/pkg/db"
	"lottery/pkg/schemas"

	"github.com/gin-gonic/gin"
)

func CreateSchemeWrapper(d *sql.DB) gin.HandlerFunc {
	return func(ctx *gin.Context) {
		newScheme := &schemas.NewScheme{}
		// Bind the incoming JSON request to the variables
		if err := ctx.ShouldBindJSON(newScheme); err != nil {
			ctx.JSON(400, gin.H{"error": "Invalid input data"})
		}

		// Call the CreateScheme function to handle the creation logic
		if err := db.InsertScheme(d, newScheme.Name, newScheme.Numbers); err != nil {
			ctx.JSON(500, gin.H{"error": "Failed to create scheme"})
			return
		}

		ctx.JSON(201, gin.H{"message": "Scheme created successfully"})
	}
}
