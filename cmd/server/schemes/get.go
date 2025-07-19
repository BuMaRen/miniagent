package schemes

import (
	"database/sql"
	"lottery/cmd/pkg/db"

	"github.com/gin-gonic/gin"
	slog "github.com/stainton/logger"
)

func GetAllSchemesWrapper(logger slog.Logger, d *sql.DB) gin.HandlerFunc {
	return func(ctx *gin.Context) {
		// Call the GetAllSchemes function to handle the logic of retrieving all schemes
		schemes, err := db.QuerySchemes(d)
		if err != nil {
			logger.Errorf("查询schemes表中的全量数据失败：%+v", err)
			ctx.JSON(500, gin.H{"error": err.Error()})
			return
		}
		ctx.JSON(200, schemes)
	}
}
