const apiBase = 'http://localhost:9090';

// 获取方案列表
function loadSchemes() {
  axios.get(`${apiBase}/schemes`)
    .then(res => {
      const tbody = document.querySelector("#schemeTable tbody");
      tbody.innerHTML = "";
      res.data.forEach(item => {
        tbody.innerHTML += `
          <tr>
            <td>${item.id}</td>
            <td>${item.name}</td>
            <td>${item.numbers}</td>
            <td><button class="btn btn-danger btn-sm" onclick="deleteScheme(${item.id})">删除</button></td>
          </tr>`;
      });
    });
}

// 添加方案
function addScheme() {
  const name = document.getElementById("schemeName").value;
  const numbers = document.getElementById("schemeNumbers").value;
  axios.post(`${apiBase}/schemes`, { name, numbers })
    .then(() => {
      loadSchemes();
      alert("添加成功");
    });
}

// 删除方案
function deleteScheme(id) {
  axios.delete(`${apiBase}/schemes/${id}`)
    .then(() => {
      loadSchemes();
      alert("删除成功");
    });
}

window.onload = loadSchemes;
