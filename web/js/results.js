const apiBase = 'http://localhost:9090';

function checkResults() {
  const numbers = document.getElementById("drawNumbers").value;
  axios.post(`${apiBase}/results/check`, { numbers })
    .then(res => {
      const tbody = document.querySelector("#resultTable tbody");
      tbody.innerHTML = res.data.map(item => `<tr>
        <td>${item.username}</td>
        <td>${item.scheme_name}</td>
        <td>${item.price}</td>
        <td>${item.created_at}</td>
      </tr>`
      ).join("");
    });
}
