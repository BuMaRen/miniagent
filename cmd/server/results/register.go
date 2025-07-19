package results

import (
	"database/sql"

	"github.com/gin-gonic/gin"
	slog "github.com/stainton/logger"
)

func RegisterHandler(logger slog.Logger, db *sql.DB, router *gin.Engine) {
	router.POST("/results/check", QueryResultsWrapper(logger, db))
}
