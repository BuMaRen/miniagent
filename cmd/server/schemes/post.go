package schemes

import (
	"database/sql"
	"lottery/cmd/pkg/db"
	"lottery/pkg/schemas"

	"github.com/gin-gonic/gin"
	slog "github.com/stainton/logger"
)

func CreateSchemeWrapper(logger slog.Logger, d *sql.DB) gin.HandlerFunc {
	return func(ctx *gin.Context) {
		newScheme := &schemas.NewScheme{}
		// Bind the incoming JSON request to the variables
		if err := ctx.ShouldBindJSON(newScheme); err != nil {
			logger.Errorf("新增scheme的时候解析payload失败：%+v", err)
			ctx.JSON(400, gin.H{"error": err.Error()})
			ctx.Abort()
			return
		}

		// Call the CreateScheme function to handle the creation logic
		if err := db.InsertScheme(d, newScheme.Name, newScheme.Numbers); err != nil {
			logger.Errorf("新增scheme失败：%+v", err)
			ctx.JSON(500, gin.H{"error": err.Error()})
			ctx.Abort()
			return
		}

		ctx.JSON(201, gin.H{"message": "Scheme created successfully"})
	}
}
