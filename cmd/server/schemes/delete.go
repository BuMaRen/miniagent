package schemes

import (
	"database/sql"
	"lottery/cmd/pkg/db"
	"strconv"

	"github.com/gin-gonic/gin"
)

func DeleteSchemeWrapper(d *sql.DB) gin.HandlerFunc {
	return func(ctx *gin.Context) {
		// Extract the scheme ID from the request parameters
		id := ctx.Param("id")
		schemeID, err := strconv.Atoi(id)
		if err != nil {
			ctx.JSON(400, gin.H{"error": "Invalid scheme ID"})
			return
		}
		// Call the DeleteScheme function to handle the deletion logic
		if err = db.DeleteScheme(d, schemeID); err != nil {
			ctx.JSON(500, gin.H{"error": "Failed to delete scheme"})
			return
		}

		ctx.JSON(200, gin.H{"message": "Scheme deleted successfully"})
	}
}
