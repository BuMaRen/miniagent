package results

import (
	"database/sql"
	"lottery/cmd/pkg/db"
	"lottery/pkg/schemas"
	"strconv"

	"github.com/gin-gonic/gin"
)

func QueryResultsWrapper(d *sql.DB) gin.HandlerFunc {
	return func(ctx *gin.Context) {
		numbers := &schemas.DrawNumbers{}
		if err := ctx.ShouldBindJSON(numbers); err != nil {
			ctx.JSON(400, gin.H{"error": "Invalid input"})
			return
		}
		number, err := strconv.Atoi(numbers.Numbers)
		if err != nil {
			ctx.JSON(400, gin.H{"error": "Invalid number format"})
			return
		}
		winners, err := db.QueryResults(d, number)
		if err != nil {
			ctx.JSON(500, gin.H{"error": "Failed to query results"})
			return
		}
		if len(winners) == 0 {
			ctx.JSON(404, gin.H{"message": "No winners found"})
			return
		}
		ctx.JSON(200, winners)
	}
}
