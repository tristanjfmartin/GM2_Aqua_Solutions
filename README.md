# Technology for the Poorest Billion (GM2): Aqua Solutions

This repository was created by Aidan O'Donnell (ao565) and Tristan Martin (tjfm4) in conjunction with Allen Chafa, founder of Aqua Solutions, as a part of the four-week GM2 IIA CUED project. This was the first year students from GM2 collaborated with Aqua Solutions. 

## Repository Structure
- Admin:
  - issues: Resolved, live, and forecasted challenges with both the technical and implementation complexities of deploying this product.
  - Meetings: Notes on meetings with Allen Chafa and supervisors (Dr.Allen, Dr.Bashford, and Dr.Smith).
  - Plans: Plans for our approach to each objective. Each time we pivot or define a new objective, we create a new document to outline what we want to do and how we plan to get there. 
- App: 
- Data:
  - Datasets: Four publicly available water quality datasets.
  - ML: All machine learning work. Includes XGBoost and logistic regression analyses on existing datasets and a complete XGBoost pipeline, (Compressed Bootstrap) ready to train on real sensor and illness-report data once it is collected, with a synthetic data placeholder.
  - Labelling: Logic for converting illness reports into confidence-weighted training labels. 
  - plan.md: Decisions on which datasets to analyse and why.
- Research: Documents, papers, and case studies used to understand current ML techniques for water quality tasks and the digital healthcare systems in place in Zimbabwe.

## Allen Chafa: 
https://reports.raeng.org.uk/africa-prize-2023-interactive-showcase/allen-chafa.html

## Deliverables: 
- [Final Pre-Recorded Video Presentation](Final_Presentation.mp4)
- [Final Presentation Slideshow](/Admin/Presentations/Final_Presentation.pdf)
- [Webpage](https://tristanjfmartin.github.io/GM2_Aqua_Solutions/)
- Individual Reports, SDG Document, Project Management Document, and Project Summary Documents are under the Wiki section.

## Risk Assessment: 
Over the four weeks the students worked on this project, they used a variety of software approaches. Therefore, there was very little risk involved, unlike for other groups which were using machining equipment. While it is the hope that future students will work on the microcontroller that forms the physical device for data collection, this was outside of the scope of the four weeks dedicated to this project. Nonetheless, a risk assessment was submitted through the CUED Power App for soldering.

## AI Declaration
AI-assisted development was used to accelerate code iteration, given the four-week project timeline, to avoid spending the majority of the project on syntax rather than design decisions. This included parts of the initial XGBoost analysis on existing datasets, Flask web application scaffolding and general code debugging. All design decisions, problem scoping and technical judgements were made by the student team. AI-generated code was reviewed and tested, with the student team taking responsibility for its correctness and integration. The core deliverables of the final handover, the compressed XGBoost bootstrap pipeline and the DHIS2 reporting interface integration, were done manually by the student team.
