package schemes

import (
	"database/sql"

	"github.com/gin-gonic/gin"
)

func RegisterHandlers(db *sql.DB, router *gin.Engine) {
	router.GET("/schemes", GetAllSchemesWrapper(db))
	router.POST("/schemes", CreateSchemeWrapper(db))
	router.DELETE("/schemes/:id", DeleteSchemeWrapper(db))
}
