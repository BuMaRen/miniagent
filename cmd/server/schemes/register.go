package schemes

import "github.com/gin-gonic/gin"

func RegisterHandlers(router *gin.Engine) {
	router.GET("/schemes", GetAllSchemes)
	router.POST("/schemes", CreateScheme)
	router.DELETE("/schemes/:id", DeleteScheme)
}
