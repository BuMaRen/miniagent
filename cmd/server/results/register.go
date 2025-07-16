package results

import "github.com/gin-gonic/gin"

func RegisterHandler(router *gin.Engine) {
	router.POST("/results/check", QueryResults)
}
