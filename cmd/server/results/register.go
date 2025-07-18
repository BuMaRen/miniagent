package results

import (
	"database/sql"

	"github.com/gin-gonic/gin"
)

func RegisterHandler(db *sql.DB, router *gin.Engine) {
	router.POST("/results/check", QueryResultsWrapper(db))
}
