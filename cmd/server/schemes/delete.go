package schemes

import (
	"database/sql"
	"lottery/cmd/pkg/db"
	"strconv"

	"github.com/gin-gonic/gin"
	slog "github.com/stainton/logger"
)

func DeleteSchemeWrapper(logger slog.Logger, d *sql.DB) gin.HandlerFunc {
	return func(ctx *gin.Context) {
		// Extract the scheme ID from the request parameters
		id := ctx.Param("id")
		schemeID, err := strconv.Atoi(id)
		if err != nil {
			logger.Errorf("解析url中的id失败：%+v", err)
			ctx.JSON(400, gin.H{"error": "Invalid scheme ID"})
			ctx.Abort()
			return
		}
		// Call the DeleteScheme function to handle the deletion logic
		if err = db.DeleteScheme(d, schemeID); err != nil {
			logger.Errorf("删除schemes表中的数据失败：%+v", err)
			ctx.JSON(500, gin.H{"error": err.Error()})
			ctx.Abort()
			return
		}

		ctx.JSON(200, gin.H{"message": "Scheme deleted successfully"})
	}
}
