package schemes

import (
	"database/sql"
	"lottery/cmd/pkg/db"

	"github.com/gin-gonic/gin"
)

var schemesTableExists = false

func schemesTableWrapper(d *sql.DB, handler func(*sql.DB) gin.HandlerFunc) gin.HandlersChain {
	return gin.HandlersChain{
		func(c *gin.Context) {
			if !schemesTableExists {
				err := db.CreateSchemesTable(d)
				if err != nil {
					c.JSON(500, gin.H{"error": err.Error()})
					c.Abort()
					return
				}
				schemesTableExists = true
			}
			c.Next()
		},
		handler(d),
	}
}

func RegisterHandlers(d *sql.DB, router *gin.Engine) {
	router.GET("/schemes", schemesTableWrapper(d, GetAllSchemesWrapper)...)
	router.POST("/schemes", schemesTableWrapper(d, CreateSchemeWrapper)...)
	router.DELETE("/schemes/:id", schemesTableWrapper(d, DeleteSchemeWrapper)...)
}
