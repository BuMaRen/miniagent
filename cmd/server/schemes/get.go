package schemes

import (
	"database/sql"
	"lottery/cmd/pkg/db"

	"github.com/gin-gonic/gin"
)

func GetAllSchemes(ctx *gin.Context) {}

func GetAllSchemesWrapper(d *sql.DB) gin.HandlerFunc {
	return func(ctx *gin.Context) {
		// Call the GetAllSchemes function to handle the logic of retrieving all schemes
		schemes, err := db.QuerySchemes(d)
		if err != nil {
			ctx.JSON(500, gin.H{"error": "Failed to retrieve schemes"})
			return
		}

		ctx.JSON(200, schemes)
	}
}
